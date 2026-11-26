"""Docker-isolated execution for the supported Python and C++ languages."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

MAX_CODE_BYTES = 2 * 1024 * 1024
MAX_STDIN_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
EXECUTION_TIMEOUT_SECONDS = 5
COMPILATION_TIMEOUT_SECONDS = 10
RUNNER_IMAGE = os.environ.get("CODESCRIBE_RUNNER_IMAGE", "codescribe-runner:latest")
MAX_CONCURRENT_RUNS = 2

_execution_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


class RunnerUnavailable(Exception):
    """Raised when the required Docker execution sandbox is unavailable."""


class RunnerBusy(Exception):
    """Raised when all local execution slots are occupied."""


@dataclass
class ExecutionResult:
    status: str
    stdout: str
    stderr: str
    execution_time_ms: int


def _limited_text(content, truncated):
    marker = "\n[output truncated]"
    marker_bytes = marker.encode("utf-8") if truncated else b""
    content_limit = MAX_OUTPUT_BYTES - len(marker_bytes)
    text = bytes(content[:content_limit]).decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    if len(encoded) > content_limit:
        text = encoded[:content_limit].decode("utf-8", errors="ignore")
    return text + marker


def _capture_process(command, stdin_text, timeout_seconds):
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise RunnerUnavailable("Docker CLI is not installed.") from error

    collected = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def drain(name, stream):
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            remaining = MAX_OUTPUT_BYTES - len(collected[name])
            if remaining > 0:
                collected[name].extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated[name] = True

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True)
    ]
    for reader in readers:
        reader.start()

    def write_input():
        try:
            process.stdin.write(stdin_text.encode("utf-8"))
            process.stdin.close()
        except BrokenPipeError:
            pass

    writer = threading.Thread(target=write_input, daemon=True)
    writer.start()

    timed_out = False
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        return_code = process.wait()

    writer.join(timeout=1)
    for reader in readers:
        reader.join()

    return (
        return_code,
        _limited_text(collected["stdout"], truncated["stdout"]),
        _limited_text(collected["stderr"], truncated["stderr"]),
        timed_out
    )


def _docker_command(command, timeout_seconds=10):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False
        )
    except FileNotFoundError as error:
        raise RunnerUnavailable(
            "Docker CLI is not installed. Install and start Docker Desktop, then build "
            "the runner image with: docker build -f Dockerfile.runner "
            "-t codescribe-runner:latest ."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise RunnerUnavailable("Docker did not respond in time. Start Docker Desktop and retry.") from error

    if result.returncode:
        if command[1:2] == ["info"]:
            raise RunnerUnavailable("Docker daemon is unavailable. Start Docker Desktop and retry.")
        if command[1:2] == ["image"]:
            raise RunnerUnavailable(
                f"Runner image '{RUNNER_IMAGE}' is unavailable. From the project root, run: "
                f"docker build -f Dockerfile.runner -t {RUNNER_IMAGE} ."
            )
        if command[1:2] in (["create"], ["start"]):
            raise RunnerUnavailable("Docker could not start the sandbox container. Check Docker Desktop.")
        raise RunnerUnavailable("The Docker runner image or daemon is unavailable.")
    return result.stdout.strip()


def _ensure_sandbox_ready():
    _docker_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout_seconds=5)
    _docker_command(["docker", "image", "inspect", RUNNER_IMAGE], timeout_seconds=5)


def _create_container(source_dir, container_name):
    source_path = str(source_dir.resolve())
    if os.name == "nt":
        source_path = source_path.replace("\\", "/")

    return _docker_command([
        "docker", "create",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m",
        "--memory", "128m",
        "--memory-swap", "128m",
        "--cpus", "0.5",
        "--pids-limit", "64",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", f"type=bind,source={source_path},target=/workspace,readonly",
        "--workdir", "/workspace",
        RUNNER_IMAGE,
        "sleep", "60"
    ])


def _remove_container(container_name):
    try:
        result = subprocess.run(
            ["docker", "rm", "--force", container_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
    except FileNotFoundError as error:
        raise RunnerUnavailable("Docker CLI became unavailable during cleanup.") from error
    except subprocess.TimeoutExpired as error:
        raise RunnerUnavailable("Docker could not clean up the execution container.") from error

    if result.returncode:
        raise RunnerUnavailable("Docker could not clean up the execution container.")


def run_code(language, code, stdin=""):
    """Run code in a resource-limited container; never execute on the host."""
    if language not in ("python", "cpp"):
        raise ValueError("Unsupported language.")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Code content is empty.")
    try:
        code_size = len(code.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValueError("Code content must be valid UTF-8 text.") from error
    if code_size > MAX_CODE_BYTES:
        raise ValueError("Code content exceeds the 2MB limit.")
    if not isinstance(stdin, str):
        raise ValueError("Standard input must be text.")
    try:
        stdin_size = len(stdin.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValueError("Standard input must be valid UTF-8 text.") from error
    if stdin_size > MAX_STDIN_BYTES:
        raise ValueError("Standard input exceeds the 64KB limit.")
    if not _execution_slots.acquire(blocking=False):
        raise RunnerBusy("All execution slots are currently busy.")

    try:
        _ensure_sandbox_ready()
        with tempfile.TemporaryDirectory(prefix="codescribe-run-") as directory:
            source_dir = Path(directory)
            source_name = "main.py" if language == "python" else "main.cpp"
            (source_dir / source_name).write_text(code, encoding="utf-8")
            container_name = f"codescribe-{uuid.uuid4().hex}"
            created = False
            started_at = time.monotonic()
            try:
                _create_container(source_dir, container_name)
                created = True
                _docker_command(["docker", "start", container_name], timeout_seconds=5)

                if language == "python":
                    return_code, stdout, stderr, timed_out = _capture_process(
                        ["docker", "exec", "--interactive", container_name,
                         "python3", "-I", "-B", "/workspace/main.py"],
                        stdin,
                        EXECUTION_TIMEOUT_SECONDS
                    )
                    status = "Time Limit Exceeded" if timed_out else (
                        "Success" if return_code == 0 else "Runtime Error"
                    )
                else:
                    compile_code, compile_stdout, compile_stderr, timed_out = _capture_process(
                        ["docker", "exec", container_name, "g++", "-O2", "-std=c++17",
                         "/workspace/main.cpp", "-o", "/tmp/codescribe-program"],
                        "",
                        COMPILATION_TIMEOUT_SECONDS
                    )
                    if timed_out:
                        status = "Time Limit Exceeded"
                        stdout, stderr = compile_stdout, compile_stderr
                    elif compile_code != 0:
                        status = "Compilation Error"
                        stdout, stderr = compile_stdout, compile_stderr
                    else:
                        return_code, stdout, stderr, timed_out = _capture_process(
                            ["docker", "exec", "--interactive", container_name,
                             "/tmp/codescribe-program"],
                            stdin,
                            EXECUTION_TIMEOUT_SECONDS
                        )
                        status = "Time Limit Exceeded" if timed_out else (
                            "Success" if return_code == 0 else "Runtime Error"
                        )

                execution_time_ms = int((time.monotonic() - started_at) * 1000)
                return ExecutionResult(status, stdout, stderr, execution_time_ms)
            finally:
                if created:
                    _remove_container(container_name)
    finally:
        _execution_slots.release()
