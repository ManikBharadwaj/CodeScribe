"""
CodeScribe Comprehensive Backend Smoke Test Suite
Executes end-to-end tests across all 5 backend blocks using Flask's test client.
"""

import json
import os
import sys
from unittest.mock import patch
from app import create_app
from models import db
from runner import ExecutionResult, RunnerUnavailable, _capture_process


def run_smoke_tests():
    print("=" * 70)
    print("CODESCRIBE BACKEND SMOKE TEST SUITE")
    print("=" * 70)

    # Set test environment to use isolated in-memory SQLite database
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    client = app.test_client()

    passed = 0
    total = 0

    def assert_test(name, condition, details=""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name} - {details}")

    # -------------------------------------------------------------------
    # BLOCK 1: Health & Server Setup
    # -------------------------------------------------------------------
    print("\n--- BLOCK 1: Health & Server Setup ---")
    res = client.get("/api/health")
    data = res.get_json()
    assert_test("Health Check HTTP 200", res.status_code == 200)
    assert_test("Health Check Payload Status OK", data.get("status") == "ok")

    res = client.get("/api/nonexistent-route")
    assert_test("Custom 404 Handler Returns JSON Error", res.status_code == 404 and "error" in res.get_json())

    # -------------------------------------------------------------------
    # BLOCK 2 & 3: Auth & User Workspaces
    # -------------------------------------------------------------------
    print("\n--- BLOCK 2 & 3: Authentication & User Workspaces ---")

    # 1. Unauthenticated check
    res = client.get("/api/auth/me")
    assert_test("Unauthenticated /me returns 401", res.status_code == 401)
    res = client.post("/api/run", json={"language": "python", "code": "print(1)"})
    assert_test("Unauthenticated code execution returns 401", res.status_code == 401)

    # 2. Register User 1
    alice_payload = {
        "full_name": "Alice Engineer",
        "email": "alice@example.com",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123"
    }
    res = client.post("/api/auth/register", json=alice_payload)
    assert_test("Register Alice HTTP 201", res.status_code == 201)
    data = res.get_json()
    assert_test("Default workspace created on registration", "default_workspace_id" in data)

    # 3. Duplicate registration check
    res = client.post("/api/auth/register", json=alice_payload)
    assert_test("Duplicate registration returns 400", res.status_code == 400)

    # 4. Check session /me
    res = client.get("/api/auth/me")
    assert_test("Authenticated /me returns user profile", res.status_code == 200 and res.get_json()["user"]["email"] == "alice@example.com")

    # 5. List workspaces for Alice
    res = client.get("/api/workspaces")
    assert_test("List Alice workspaces HTTP 200", res.status_code == 200)
    workspaces = res.get_json()["workspaces"]
    assert_test("Alice has initial default workspace", len(workspaces) == 1)
    alice_ws_id = workspaces[0]["id"]

    # 6. Create additional workspace
    res = client.post("/api/workspaces", json={"name": "Data Structures Project", "description": "Trees and Graphs"})
    assert_test("Create workspace HTTP 201", res.status_code == 201)
    data = res.get_json()
    alice_ds_ws_id = data["workspace"]["id"]

    # 7. Register User 2 (Bob)
    client.post("/api/auth/logout")  # Log out Alice
    bob_payload = {
        "full_name": "Bob Developer",
        "email": "bob@example.com",
        "password": "BobSecurePassword123",
        "confirm_password": "BobSecurePassword123"
    }
    client.post("/api/auth/register", json=bob_payload)

    # 8. Ownership Protection Check: Bob tries to access Alice's workspace
    res = client.get(f"/api/workspaces/{alice_ws_id}")
    assert_test("Ownership check blocks unauthorized workspace access (403)", res.status_code == 403)

    # -------------------------------------------------------------------
    # BLOCK 4: AST & Structural Code Analysis Engine
    # -------------------------------------------------------------------
    print("\n--- BLOCK 4: AST & Structural Code Analysis ---")

    # Log back in as Alice
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "alice@example.com", "password": "SecurePassword123"})

    # Isolated execution route validation and response contract
    res = client.post("/api/run", json={"language": "ruby", "code": "puts 1"})
    assert_test("Execution rejects unsupported languages", res.status_code == 400)
    res = client.post("/api/run", json={"language": "python", "code": ["not", "text"]})
    assert_test("Execution rejects non-text source", res.status_code == 400)
    with patch("app.run_code", return_value=ExecutionResult("Success", "42\n", "", 12)) as mock_runner:
        res = client.post(
            "/api/run",
            json={"language": "python", "code": "print(42)", "stdin": ""}
        )
    run_result = res.get_json()
    assert_test("Execution route returns the documented result shape",
                res.status_code == 200 and run_result == {
                    "status": "Success",
                    "stdout": "42\n",
                    "stderr": "",
                    "execution_time_ms": 12
                })
    assert_test("Execution route passes only the requested language, code, and stdin",
                mock_runner.call_args.args == ("python", "print(42)", ""))
    with patch("app.run_code", side_effect=RunnerUnavailable("Docker CLI is not installed.")):
        res = client.post("/api/run", json={"language": "cpp", "code": "int main() {}"})
    assert_test("Execution fails closed when the Docker sandbox is unavailable",
                res.status_code == 503
                and res.get_json()["error"] == "Docker CLI is not installed.")
    output_result = _capture_process(
        [sys.executable, "-c",
         "import sys; sys.stdout.write('o' * 70000); sys.stderr.write('e' * 70000)"],
        "",
        5
    )
    assert_test("Runner capture caps stdout and stderr independently",
                len(output_result[1].encode("utf-8")) <= 64 * 1024
                and len(output_result[2].encode("utf-8")) <= 64 * 1024
                and output_result[1].endswith("[output truncated]")
                and output_result[2].endswith("[output truncated]"))
    timeout_result = _capture_process(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        "",
        0.1
    )
    assert_test("Runner capture reports timed-out processes", timeout_result[3] is True)

    # 1. Valid Python Code File & AST Analysis
    python_valid_code = """
def is_even(num):
    if num % 2 == 0:
        return True
    return False

def count_evens(numbers):
    count = 0
    for n in numbers:
        if is_even(n):
            count += 1
    return count

nums = [1, 2, 3, 4, 5, 6]
print("Evens count:", count_evens(nums))
"""
    res = client.post(
        f"/api/workspaces/{alice_ws_id}/files",
        json={"name": "even_counter.py", "language": "python", "content": python_valid_code}
    )
    assert_test("Save valid Python file HTTP 201", res.status_code == 201)
    data = res.get_json()
    py_file_id = data["file"]["id"]
    analysis = data["analysis"]

    assert_test("AST Syntax Valid Flag is True", analysis["valid_syntax"] is True)
    assert_test("AST Function Count (Expected: 2)", analysis["metrics"]["functions"] == 2, f"Got: {analysis['metrics']['functions']}")
    assert_test("AST Loop Count (Expected: 1)", analysis["metrics"]["loops"] == 1, f"Got: {analysis['metrics']['loops']}")
    assert_test("AST Conditional Count (Expected: 2)", analysis["metrics"]["conditionals"] == 2, f"Got: {analysis['metrics']['conditionals']}")
    assert_test("AST Cyclomatic Complexity Score Calculated", analysis["metrics"]["cyclomatic_complexity"] >= 5)

    # 2. Invalid Python Code with Syntax Error
    python_broken_code = """
def broken_function(x, y:
    return x + y
"""
    res = client.post(
        f"/api/workspaces/{alice_ws_id}/files",
        json={"name": "broken.py", "language": "python", "content": python_broken_code}
    )
    assert_test("Save broken Python file HTTP 201", res.status_code == 201)
    data = res.get_json()
    analysis = data["analysis"]

    assert_test("AST Syntax Valid Flag is False for SyntaxError", analysis["valid_syntax"] is False)
    assert_test("SyntaxError diagnostic identifies line number", "error" in analysis and analysis["error"]["line"] == 2)

    # 3. Valid C++ Code & Structural Token Analysis
    cpp_valid_code = """
#include <iostream>
#include <vector>

void printVector(const std::vector<int>& vec) {
    for (int val : vec) {
        if (val > 0) {
            std::cout << val << std::endl;
        }
    }
}

int main() {
    std::vector<int> numbers = {1, 2, 3};
    printVector(numbers);
    return 0;
}
"""
    res = client.post(
        f"/api/workspaces/{alice_ws_id}/files",
        json={"name": "main.cpp", "language": "cpp", "content": cpp_valid_code}
    )
    assert_test("Save C++ file HTTP 201", res.status_code == 201)
    data = res.get_json()
    cpp_analysis = data["analysis"]
    cpp_file_id = data["file"]["id"]

    assert_test("C++ Analysis Language Identified", cpp_analysis["language"] == "cpp")
    assert_test("C++ Function Detection (Expected: 2)", cpp_analysis["metrics"]["functions"] == 2, f"Got: {cpp_analysis['metrics']['functions']}")
    assert_test("C++ Includes Detection (Expected: 2)", cpp_analysis["metrics"]["includes"] == 2, f"Got: {cpp_analysis['metrics']['includes']}")
    update_res = client.put(
        f"/api/files/{cpp_file_id}",
        json={"name": "main.cpp", "language": "cpp", "content": "int main() { return 0; }"}
    )
    assert_test("Update existing file preserves API and returns analysis",
                update_res.status_code == 200 and update_res.get_json()["analysis"]["language"] == "cpp")

    # 4. Raw AST Analysis Endpoint
    res = client.post("/api/analyze-raw", json={"content": "x = [i for i in range(10) if i % 2 == 0]", "language": "python"})
    assert_test("Raw analyze endpoint HTTP 200", res.status_code == 200)

    nested_python = "\n".join([
        "def scan(items):",
        "    seen = []",
        "    for first in items:",
        "        for second in items:",
        "            if second in items:",
        "                seen.append(second)",
        "    return seen"
    ])
    res = client.post("/api/analyze-raw", json={"content": nested_python, "language": "python"})
    analysis = res.get_json()
    concepts_by_name = {item["name"]: item["lines"] for item in analysis.get("concepts", [])}
    assert_test("Python concepts include exact function and loop lines",
                res.status_code == 200 and concepts_by_name.get("Function") == [1]
                and concepts_by_name.get("Loop") == [3, 4])
    assert_test("Python nested-loop complexity spike is line-mapped",
                analysis.get("metrics", {}).get("max_loop_depth") == 2
                and analysis.get("complexity", {}).get("spikes", [{}])[0].get("line") == 4)
    assert_test("Python complexity hint is step-by-step and solution-free",
                any(hint.get("line") == 4 and len(hint.get("steps", [])) >= 3
                    for hint in analysis.get("hints", [])))

    res = client.post("/api/analyze-raw", json={"content": "def broken(:\n    pass", "language": "python"})
    analysis = res.get_json()
    assert_test("Raw Python syntax error has an exact line and hint",
                res.status_code == 200 and analysis.get("error", {}).get("line") == 1
                and analysis.get("hints", [{}])[0].get("line") == 1)

    nested_cpp = "\n".join([
        "#include <vector>",
        "void scan(std::vector<int>& items) {",
        "  for (int first : items) {",
        "    for (int second : items) {",
        "      if (second > 0) {}",
        "    }",
        "  }",
        "}"
    ])
    res = client.post("/api/analyze-raw", json={"content": nested_cpp, "language": "cpp"})
    analysis = res.get_json()
    concepts_by_name = {item["name"]: item["lines"] for item in analysis.get("concepts", [])}
    assert_test("C++ vector and nested-loop concepts have exact lines",
                res.status_code == 200 and concepts_by_name.get("Vector") == [2]
                and concepts_by_name.get("Loop") == [3, 4])
    assert_test("C++ estimate is labeled structural and includes a hint",
                analysis.get("syntax_checked") is False
                and analysis.get("metrics", {}).get("max_loop_depth") == 2
                and any(hint.get("line") == 4 for hint in analysis.get("hints", [])))

    res = client.post("/api/analyze-raw", json={"content": "int main() {\n return 0;\n", "language": "cpp"})
    analysis = res.get_json()
    assert_test("C++ unmatched delimiter returns a line-specific structural hint",
                res.status_code == 200 and analysis.get("valid_syntax") is False
                and analysis.get("error", {}).get("line") == 1
                and analysis.get("hints", [{}])[0].get("line") == 1)
    assert_test("Empty raw source returns a clean client error",
                client.post("/api/analyze-raw", json={"content": "  ", "language": "python"}).status_code == 400)
    assert_test("Unsupported raw language is rejected",
                client.post("/api/analyze-raw", json={"content": "print(1)", "language": "ruby"}).status_code == 400)
    assert_test("Non-object raw JSON is rejected cleanly",
                client.post("/api/analyze-raw", json=["not", "an", "object"]).status_code == 400)
    assert_test("Oversized raw source is rejected with HTTP 413",
                client.post("/api/analyze-raw",
                            json={"content": "x" * (2 * 1024 * 1024 + 1), "language": "python"}).status_code == 413)
    assert_test("Mismatched file extension and language are rejected",
                client.post(f"/api/workspaces/{alice_ws_id}/files",
                            json={"name": "mismatch.py", "language": "cpp", "content": "int main() {}"}).status_code == 400)

    # -------------------------------------------------------------------
    # BLOCK 5: Defensive Security & Cleanup Tests
    # -------------------------------------------------------------------
    print("\n--- BLOCK 5: Defensive Security & Cleanup ---")

    # 1. Path Traversal & Disallowed Extension Check
    res = client.post(
        f"/api/workspaces/{alice_ws_id}/files",
        json={"name": "../../../etc/passwd.exe", "language": "exe", "content": "malicious"}
    )
    assert_test("Disallowed file extension rejected (400)", res.status_code == 400)

    # 2. File Deletion
    res = client.delete(f"/api/files/{py_file_id}")
    assert_test("File deletion HTTP 200", res.status_code == 200)

    # 3. Workspace Deletion (Cascades to files)
    res = client.delete(f"/api/workspaces/{alice_ds_ws_id}")
    assert_test("Workspace deletion HTTP 200", res.status_code == 200)

    # 4. Logout verification
    client.post("/api/auth/logout")
    res = client.get("/api/auth/me")
    assert_test("Logout clears session (/me returns 401)", res.status_code == 401)

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} / {total} tests passed ({int(passed / total * 100)}%)")
    print("=" * 70)

    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    run_smoke_tests()
