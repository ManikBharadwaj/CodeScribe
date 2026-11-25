"""
CodeScribe static analysis for Python ASTs and C++ source structure.
"""

import ast
from bisect import bisect_right
import re

MAX_ANALYSIS_CHARS = 2 * 1024 * 1024
MAX_AST_NODES = 100_000
MAX_SOURCE_LINES = 100_000


def _source_line_count(code):
    if not code:
        return 0
    breaks = sum(1 for _ in re.finditer(r"\r\n|[\r\n]", code))
    return breaks if code.endswith(("\n", "\r")) else breaks + 1


def _concepts_from_lines(found):
    return [
        {"name": name, "lines": sorted(set(lines))}
        for name, lines in sorted(found.items())
        if lines
    ]


def _failure(language, code, message, line=0, offset=0, text=""):
    lines = code.splitlines()
    blank_lines = sum(not item.strip() for item in lines)
    comment_lines = sum(item.strip().startswith("#") for item in lines) if language == "python" else 0
    return {
        "valid_syntax": False,
        "syntax_checked": language == "python",
        "language": language,
        "error": {
            "line": line,
            "offset": offset,
            "message": message,
            "text": text.strip()
        },
        "metrics": {
            "total_lines": len(lines),
            "sloc": max(0, len(lines) - blank_lines - comment_lines),
            "comment_lines": comment_lines,
            "blank_lines": blank_lines
        },
        "concepts": [],
        "complexity": {"time": "Not estimated", "space": "Not estimated", "spikes": []},
        "suggestions": [],
        "hints": [{
            "line": line,
            "title": "Syntax needs a closer look",
            "steps": [
                "Start at the reported line and inspect the nearest open bracket, quote, or statement.",
                "Compare the surrounding block's indentation and punctuation.",
                "Fix one issue, then analyze again to reveal the next parser hint."
            ]
        }],
        "summary": f"Python parse issue at line {line}: {message}" if language == "python"
        else f"Static analysis unavailable: {message}"
    }


def _analysis_limit(language, message, line=0):
    return {
        "valid_syntax": False,
        "syntax_checked": language == "python",
        "error_type": "analysis_limit",
        "language": language,
        "error": {"line": line, "offset": 0, "message": message, "text": ""},
        "metrics": {
            "total_lines": line,
            "sloc": 0,
            "comment_lines": 0,
            "blank_lines": 0
        },
        "concepts": [],
        "complexity": {"time": "Not estimated", "space": "Not estimated", "spikes": []},
        "suggestions": [],
        "hints": [{
            "line": line,
            "title": "Static scan paused safely",
            "steps": [
                "Reduce the source size or split the file into smaller sections.",
                "Keep one function or logical block in the editor and analyze again."
            ]
        }],
        "summary": f"Static scan stopped safely: {message}"
    }


class PythonASTVisitor(ast.NodeVisitor):
    """Gather the original structural metrics from a Python syntax tree."""

    def __init__(self):
        self.functions = []
        self.loops = []
        self.conditionals = []
        self.classes = []
        self.imports = []
        self.decision_points = 0

    def visit_FunctionDef(self, node):
        self.functions.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.functions.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.classes.append(node)
        self.generic_visit(node)

    def visit_For(self, node):
        self.loops.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.loops.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.loops.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_If(self, node):
        self.conditionals.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.conditionals.append(node)
        self.decision_points += 1
        self.generic_visit(node)

    def visit_Import(self, node):
        self.imports.extend([node] * len(node.names))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self.imports.extend([node] * len(node.names))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.decision_points += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.decision_points += len(node.values) - 1
        self.generic_visit(node)


def _python_loop_info(node, depth=0):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        depth = 0
    is_loop = isinstance(node, (ast.For, ast.AsyncFor, ast.While))
    if is_loop:
        depth += 1
    maximum = depth
    deepest_lines = [node.lineno] if is_loop else []
    for child in ast.iter_child_nodes(node):
        child_maximum, child_lines = _python_loop_info(child, depth)
        if child_maximum > maximum:
            maximum = child_maximum
            deepest_lines = child_lines
        elif child_maximum == maximum:
            deepest_lines.extend(child_lines)
    return maximum, deepest_lines


def analyze_python_code(code_string):
    """Parse Python without execution and return metrics, concepts, and hints."""
    if not isinstance(code_string, str):
        return _failure("python", "", "Code must be text.")
    if len(code_string) > MAX_ANALYSIS_CHARS:
        return _analysis_limit("python", "Code exceeds the 2 MB analysis limit.")
    if _source_line_count(code_string) > MAX_SOURCE_LINES:
        return _analysis_limit("python", "Source exceeds the 100,000-line analysis limit.", MAX_SOURCE_LINES + 1)

    lines = code_string.splitlines()
    total_lines = len(lines)
    blank_lines = sum(not line.strip() for line in lines)
    comment_lines = sum(line.strip().startswith("#") for line in lines)
    sloc = max(0, total_lines - blank_lines - comment_lines)

    try:
        tree = ast.parse(code_string)
        visitor = PythonASTVisitor()
        visitor.visit(tree)
    except SyntaxError as error:
        return _failure(
            "python", code_string, error.msg or "Syntax error",
            error.lineno or 0, error.offset or 0, error.text or ""
        )
    except (ValueError, TypeError, OverflowError, RecursionError, MemoryError):
        return _analysis_limit("python", "The parser could not safely analyze this source.")

    found = {}

    def add(name, line):
        found.setdefault(name, set()).add(line)

    for node in visitor.functions:
        add("Function", node.lineno)
    for node in visitor.loops:
        add("Loop", node.lineno)
    for node in visitor.conditionals:
        add("Conditional", node.lineno)
        if isinstance(node, ast.If) and node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                add("Else-if branch", node.orelse[0].lineno)
            else:
                add("Else branch", node.orelse[0].lineno)
    for node in visitor.classes:
        add("Class", node.lineno)
    for node in visitor.imports:
        add("Import", node.lineno)

    all_nodes = []
    for node in ast.walk(tree):
        if len(all_nodes) >= MAX_AST_NODES:
            return _analysis_limit("python", "Code structure exceeds the static analysis limit.")
        all_nodes.append(node)
    literal_types = (
        (ast.List, ast.ListComp, "List"),
        (ast.Dict, ast.DictComp, "Dictionary"),
        (ast.Set, ast.SetComp, "Set"),
        (ast.Tuple, None, "Tuple")
    )
    for literal, comprehension, label in literal_types:
        for node in all_nodes:
            if isinstance(node, literal) or (comprehension and isinstance(node, comprehension)):
                add(label, node.lineno)

    function_names = {node.name: node for node in visitor.functions}
    recursive_functions = []
    for name, node in function_names.items():
        recursive_calls = [
            child for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == name
        ]
        if recursive_calls:
            recursive_functions.append((node, len(recursive_calls)))
            add("Recursion", node.lineno)

    method_calls = {}
    for node in all_nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            method_calls.setdefault(node.func.value.id, []).append((node.func.attr, node))
    for calls in method_calls.values():
        methods = {method for method, _ in calls}
        if "append" in methods and any(
            method == "pop" and not (
                node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0
            )
            for method, node in calls
        ):
            lines_used = [node.lineno for _, node in calls]
            add("Stack-like list operations", min(lines_used))
        if any(method == "pop" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0
               for method, node in calls) and "append" in methods:
            lines_used = [node.lineno for _, node in calls]
            add("Queue-like list operations", min(lines_used))
    for node in visitor.imports:
        if isinstance(node, ast.ImportFrom) and node.module == "collections" and any(alias.name == "deque" for alias in node.names):
            add("Queue", node.lineno)
    for node in visitor.classes:
        normalized_name = node.name.lower()
        if normalized_name in ("tree", "treenode", "binarytree"):
            add("Tree structure", node.lineno)
        elif normalized_name in ("graph", "adjacencygraph"):
            add("Graph structure", node.lineno)

    metrics = {
        "total_lines": total_lines,
        "sloc": sloc,
        "comment_lines": comment_lines,
        "blank_lines": blank_lines,
        "functions": len(visitor.functions),
        "loops": len(visitor.loops),
        "conditionals": len(visitor.conditionals),
        "classes": len(visitor.classes),
        "imports": len(visitor.imports),
        "cyclomatic_complexity": 1 + visitor.decision_points,
        "recursions": len(recursive_functions),
        "max_loop_depth": _python_loop_info(tree)[0]
    }

    max_depth = metrics["max_loop_depth"]
    if max_depth > 1:
        time_estimate = f"O(n^{max_depth}) estimated from nested loops"
    elif visitor.loops:
        time_estimate = "O(n) estimated from loop structure"
    elif recursive_functions:
        time_estimate = "Recursive; growth depends on the number of recursive calls"
    else:
        time_estimate = "O(1) structural estimate; input-dependent library calls may change this"

    grows_collection = any(
        isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp))
        for node in all_nodes
    ) or any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("append", "add", "update", "extend")
        for node in all_nodes
    )
    space_estimate = "O(n) possible when the detected collection grows with input" if grows_collection else "O(1) additional space detected; library calls are not modeled"

    spikes = []
    if max_depth > 1:
        _, deepest_lines = _python_loop_info(tree)
        spikes.extend({
            "line": line,
            "description": f"Nested loop structure reaches depth {max_depth}; time may scale with each input pass."
        } for line in sorted(set(deepest_lines))[:20])
    if recursive_functions:
        spikes.extend({
            "line": node.lineno,
            "description": f"Recursive function '{node.name}' adds call-stack depth."
        } for node, _ in recursive_functions)

    hints = []
    suggestions = []
    if max_depth > 1:
        suggestions.append({
            "line": spikes[0]["line"],
            "title": "Check repeated work in the nested loop",
            "steps": [
                "Identify which values the inner loop searches or recalculates on each outer pass.",
                "If the same membership lookup repeats, consider building a set or dictionary once.",
                "Compare the expected lookup cost with the current nested passes before changing the structure."
            ]
        })
        hints.append({
            "line": spikes[0]["line"],
            "title": "Nested passes can multiply runtime",
            "steps": [
                "Estimate how many iterations each loop can run for the same input.",
                "Check whether the inner pass repeats a search or calculation already done outside it.",
                "Compare the measured input sizes before deciding whether the structure needs to change."
            ]
        })
    if recursive_functions:
        node, _ = recursive_functions[0]
        suggestions.append({
            "line": node.lineno,
            "title": "Trace the recursive path",
            "steps": [
                "Follow one small input through every recursive branch.",
                "Confirm each branch moves toward a base case.",
                "Check whether separate branches solve the same subproblem; memoization may avoid repeated work."
            ]
        })
    for node in all_nodes:
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if visitor.loops and isinstance(node.comparators[0], (ast.Name, ast.Attribute)):
                suggestions.append({
                    "line": node.lineno,
                    "title": "Review repeated membership checks",
                    "steps": [
                        "Check whether this membership test runs once or repeatedly inside a loop.",
                        "If the collection is searched many times, compare list lookup with a set or dictionary.",
                        "Keep the current structure when ordering or duplicate behavior is required."
                    ]
                })
                break

    for node in visitor.loops:
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
            has_break = any(isinstance(child, ast.Break) for child in ast.walk(node))
            if not has_break:
                hints.append({
                    "line": node.lineno,
                    "title": "This while loop has no visible break",
                    "steps": [
                        "Trace how the loop condition changes on every pass.",
                        "Check whether any reachable branch can make the condition false.",
                        "Add or restore an exit condition if the loop is meant to finish."
                    ]
                })

    return {
        "valid_syntax": True,
        "syntax_checked": True,
        "language": "python",
        "metrics": metrics,
        "concepts": _concepts_from_lines(found),
        "complexity": {
            "time": time_estimate,
            "space": space_estimate,
            "spikes": spikes
        },
        "suggestions": suggestions,
        "hints": hints,
        "summary": (
            f"Static scan complete: {metrics['functions']} function(s), {metrics['loops']} loop(s), "
            f"{metrics['conditionals']} conditional(s), cyclomatic complexity "
            f"{metrics['cyclomatic_complexity']}."
        )
    }


def _mask_cpp_comments_and_strings(code):
    """Blank comments and quoted text while preserving source lines and offsets."""
    result = list(code)
    state = "code"
    index = 0
    while index < len(code):
        char = code[index]
        next_char = code[index + 1] if index + 1 < len(code) else ""
        if state == "code":
            if char == "/" and next_char == "/":
                result[index] = result[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if char == "/" and next_char == "*":
                result[index] = result[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if char == '"':
                result[index] = " "
                state = "string"
            elif char == "'":
                result[index] = " "
                state = "char"
        elif state in ("line_comment", "block_comment", "string", "char"):
            if char != "\n":
                result[index] = " "
            if state == "line_comment" and char == "\n":
                state = "code"
            elif state == "block_comment" and char == "*" and next_char == "/":
                result[index + 1] = " "
                state = "code"
                index += 1
            elif state in ("string", "char") and char == "\\" and index + 1 < len(code):
                result[index + 1] = " "
                index += 1
            elif state == "string" and char == '"':
                state = "code"
            elif state == "char" and char == "'":
                state = "code"
        index += 1
    return "".join(result)


def _line_number(line_starts, offset):
    return bisect_right(line_starts, offset)


def _cpp_loop_info(code):
    token_pattern = re.compile(r"\b(?:for|while|do)\b|[{}();]")
    scope_depths = [0]
    pending_loop = None
    parenthesis_depth = 0
    maximum = 0
    deepest_offsets = []
    for match in token_pattern.finditer(code):
        token = match.group()
        if token in ("for", "while", "do"):
            pending_loop = match.start()
        elif token == "(":
            parenthesis_depth += 1
        elif token == ")":
            parenthesis_depth = max(0, parenthesis_depth - 1)
        elif token == ";" and parenthesis_depth == 0:
            pending_loop = None
        elif token == "{":
            is_loop_body = pending_loop is not None
            depth = scope_depths[-1] + (1 if is_loop_body else 0)
            scope_depths.append(depth)
            if is_loop_body and depth > maximum:
                maximum = depth
                deepest_offsets = [pending_loop]
            elif is_loop_body and depth == maximum:
                deepest_offsets.append(pending_loop)
            pending_loop = None
        elif len(scope_depths) > 1:
            scope_depths.pop()
    return maximum, deepest_offsets


def analyze_cpp_code(code_string):
    """Analyze C++ structure without compiling or executing user source."""
    if not isinstance(code_string, str):
        return _failure("cpp", "", "Code must be text.")
    if len(code_string) > MAX_ANALYSIS_CHARS:
        return _analysis_limit("cpp", "Code exceeds the 2 MB analysis limit.")
    if _source_line_count(code_string) > MAX_SOURCE_LINES:
        return _analysis_limit("cpp", "Source exceeds the 100,000-line analysis limit.", MAX_SOURCE_LINES + 1)

    source = _mask_cpp_comments_and_strings(code_string)
    line_starts = [0]
    line_starts.extend(match.end() for match in re.finditer(r"\r\n|[\r\n]", source))
    lines = code_string.splitlines()
    total_lines = len(lines)
    blank_lines = sum(not line.strip() for line in lines)
    comment_lines = sum(
        line.strip().startswith("//") or line.strip().startswith("/*")
        for line in lines
    )
    sloc = max(0, total_lines - blank_lines - comment_lines)
    found = {}

    def add(name, line):
        found.setdefault(name, set()).add(line)

    patterns = {
        "Loop": r"\b(?:for|while|do)\b",
        "Conditional": r"\b(?:if|switch)\s*\(",
        "Else branch": r"\belse\b(?!\s*if\b)",
        "Header include": r"^\s*#\s*include\b",
        "Class or struct": r"\b(?:class|struct)\s+[A-Za-z_]\w*",
        "Vector": r"\b(?:std::)?vector\s*<",
        "Array": r"\b(?:std::)?array\s*<|\b[A-Za-z_]\w*\s+[A-Za-z_]\w*\s*\[\s*\d*\s*\]",
        "Map": r"\b(?:std::)?(?:unordered_map|map)\s*<",
        "Set": r"\b(?:std::)?(?:unordered_set|set)\s*<",
        "Stack": r"\b(?:std::)?stack\s*<",
        "Queue": r"\b(?:std::)?(?:queue|priority_queue)\s*<",
        "Pointer": r"\b(?:int|char|float|double|bool|void|[A-Z]\w*)\s*\*\s*[A-Za-z_]\w*"
    }
    matches = {}
    for label, pattern in patterns.items():
        occurrences = list(re.finditer(pattern, source, re.MULTILINE))
        matches[label] = occurrences
        for match in occurrences:
            add(label, _line_number(line_starts, match.start()))

    function_pattern = re.compile(
        r"^\s*(?:void|int|double|float|bool|char|std::string|auto|long|short|unsigned|uint\d+_t)"
        r"\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{",
        re.MULTILINE
    )
    function_matches = list(function_pattern.finditer(source))

    for match in function_matches:
        add("Function", _line_number(line_starts, match.start()))

    recursive_lines = []
    for function_match in function_matches:
        body_start = function_match.end() - 1
        depth = 0
        body_end = len(source)
        for index in range(body_start, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    body_end = index
                    break
        function_body = source[body_start + 1:body_end]
        name = function_match.group(1)
        if len(name) > 256:
            continue
        if re.search(rf"\b{re.escape(name)}\s*\(", function_body):
            line = _line_number(line_starts, function_match.start())
            recursive_lines.append(line)
            add("Recursion", line)

    loop_matches = matches["Loop"]
    loops = len(loop_matches)
    conditionals = len(matches["Conditional"])
    max_depth, deepest_loop_offsets = _cpp_loop_info(source)
    cyclomatic = 1 + loops + conditionals
    loop_depth = max(1, max_depth) if loops else 0
    if loop_depth > 1:
        time_estimate = f"O(n^{loop_depth}) estimated from nested loop scopes"
    elif loops:
        time_estimate = "O(n) estimated from loop structure"
    else:
        time_estimate = "O(1) structural estimate; library calls are not modeled"

    collection_names = ("Vector", "Array", "Map", "Set", "Stack", "Queue")
    space_estimate = (
        "O(n) possible when the detected container grows with input"
        if any(matches[name] for name in collection_names)
        else "O(1) additional space detected; library calls are not modeled"
    )
    spikes = []
    if loop_depth > 1:
        offsets = deepest_loop_offsets or [loop_matches[-1].start()]
        spikes.extend({
            "line": _line_number(line_starts, offset),
            "description": f"Loop nesting reaches an estimated depth of {loop_depth}."
        } for offset in offsets[:20])
    for line in recursive_lines:
        spikes.append({"line": line, "description": "Recursive call adds call-stack depth."})

    hints = []
    suggestions = []
    if loop_depth > 1:
        suggestions.append({
            "line": spikes[0]["line"],
            "title": "Inspect work repeated by nested loops",
            "steps": [
                "Check which search or calculation is repeated for each outer-loop item.",
                "If the code repeatedly searches a collection, compare an indexed map or set lookup.",
                "Confirm ordering and duplicate requirements before changing the container."
            ]
        })
        hints.append({
            "line": spikes[0]["line"],
            "title": "Nested passes can multiply runtime",
            "steps": [
                "Estimate the maximum iterations of each enclosing loop.",
                "Check whether the inner pass repeats a search or calculation for every outer item.",
                "Measure representative input sizes before deciding whether the structure needs to change."
            ]
        })
    if re.search(r"\b(?:std::)?vector\s*<", source) and re.search(r"\b(?:std::)?(?:find|count)\s*\(", source):
        line = _line_number(line_starts, re.search(r"\b(?:std::)?(?:find|count)\s*\(", source).start())
        suggestions.append({
            "line": line,
            "title": "Review repeated vector searches",
            "steps": [
                "Check whether this search runs repeatedly as input grows.",
                "For frequent membership checks, compare an unordered_set or map with a linear vector scan.",
                "Keep vector when sequential access or ordering is the main requirement."
            ]
        })
    if recursive_lines:
        suggestions.append({
            "line": recursive_lines[0],
            "title": "Trace recursive calls",
            "steps": [
                "Follow a small input through each recursive branch.",
                "Confirm every path approaches a base case.",
                "Check whether branches repeat the same subproblem before considering memoization."
            ]
        })

    structural_errors = []
    pairs = {")": "(", "]": "[", "}": "{"}
    opening = []
    for index, char in enumerate(source):
        if char in "([{":
            opening.append((char, index))
        elif char in ")]}":
            if not opening or opening[-1][0] != pairs[char]:
                structural_errors.append({
                    "line": _line_number(line_starts, index),
                    "message": f"Unmatched closing '{char}'."
                })
                break
            opening.pop()
    if not structural_errors and opening:
        char, index = opening[-1]
        structural_errors.append({
            "line": _line_number(line_starts, index),
            "message": f"Opening '{char}' has no matching closing delimiter."
        })

    for error in structural_errors:
        hints.append({
            "line": error["line"],
            "title": "Match the structural delimiter",
            "steps": [
                "Move from the reported line to the nearest opening or closing delimiter.",
                "Check the surrounding function, condition, and loop blocks as a pair.",
                "Balance the delimiters, then rerun the structural scan."
            ]
        })

    metrics = {
        "total_lines": total_lines,
        "sloc": sloc,
        "comment_lines": comment_lines,
        "blank_lines": blank_lines,
        "functions": len(function_matches),
        "loops": loops,
        "conditionals": conditionals + len(matches["Else branch"]),
        "classes": len(matches["Class or struct"]),
        "includes": len(matches["Header include"]),
        "cyclomatic_complexity": cyclomatic,
        "recursions": len(recursive_lines),
        "max_loop_depth": loop_depth
    }
    result = {
        "valid_syntax": not structural_errors,
        "syntax_checked": False,
        "analysis_kind": "structural",
        "language": "cpp",
        "metrics": metrics,
        "concepts": _concepts_from_lines(found),
        "complexity": {"time": time_estimate, "space": space_estimate, "spikes": spikes},
        "suggestions": suggestions,
        "hints": hints,
        "summary": (
            f"C++ structural scan complete: {metrics['functions']} function(s), {loops} loop(s), "
            f"{metrics['conditionals']} branch(es). Compiler syntax is not checked."
        )
    }
    if structural_errors:
        result["error"] = {
            "line": structural_errors[0]["line"],
            "offset": 0,
            "message": structural_errors[0]["message"],
            "text": lines[structural_errors[0]["line"] - 1].strip()
            if 0 < structural_errors[0]["line"] <= len(lines) else ""
        }
        result["structural_errors"] = structural_errors
    return result


def analyze_code(code_string, language="python"):
    """Dispatch static analysis for the supported languages only."""
    normalized = (language or "python").strip().lower()
    if normalized in ("py", "python"):
        return analyze_python_code(code_string)
    if normalized in ("cpp", "c++", "c", "h", "hpp"):
        return analyze_cpp_code(code_string)
    return _failure(normalized or "unknown", code_string if isinstance(code_string, str) else "", "Unsupported language. Use Python or C++.")
