"""Test HTML ID constants enforcement.

This test ensures:
1. All id= usages in src/ use constants from html_ids.py
2. All constants in html_ids.py are used in callbacks (or marked with # nocheck)

# nocheck Comment Usage:
The `# nocheck` comment allows constants to bypass test_no_unused_id_constants.
**ONLY USE # nocheck FOR THESE TWO SPECIFIC CASES:**

1. IDs accessed via set_props() in error handling (not standard callbacks)
   Example: ERROR_MODAL_MESSAGE_SHARED_ID = "error-message"  # nocheck

2. IDs used exclusively for testing/automation (not in callbacks)
   Example: JOB_SUBMISSION_LINK_SHARED_ID = "job-submission-link-shared-id"  # nocheck

**DO NOT USE # nocheck TO BYPASS THE TEST FOR OTHER REASONS!**
If a constant has # nocheck, it should match one of the two cases above.
When reviewing code, double-check all # nocheck comments to ensure they are justified.

If you find a # nocheck that doesn't fit these cases:
- Remove the ID entirely if it's truly unused
- Remove just the # nocheck if it should be used in a callback
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


def get_src_path() -> Path:
    """Get path to the cosmo_ecosystem package directory."""
    return Path(__file__).parent.parent / "cosmo_ecosystem"


def get_html_ids_path() -> Path:
    """Get path to html_ids.py file."""
    return get_src_path() / "constants" / "html_ids.py"


def load_html_ids_constants() -> Dict[str, bool]:
    """Load all ID constants from html_ids.py.

    Returns:
        Dict mapping constant name to whether it has # nocheck comment.
    """
    html_ids_file = get_html_ids_path()
    constants = {}

    with open(html_ids_file, "r") as f:
        for line in f:
            # Match pattern: CONSTANT_NAME = "value"
            match = re.match(r'^([A-Z_]+_ID)\s*=\s*"[^"]*"(.*)$', line)
            if match:
                const_name = match.group(1)
                rest_of_line = match.group(2)
                has_nocheck = "# nocheck" in rest_of_line or "#nocheck" in rest_of_line
                constants[const_name] = has_nocheck

    return constants


def find_python_files(directory: Path) -> List[Path]:
    """Find all Python files in directory recursively."""
    return list(directory.rglob("*.py"))


def is_comment_or_docstring(line: str) -> bool:
    """Check if line is a comment or likely in docstring."""
    stripped = line.strip()
    return (
        stripped.startswith("#")
        or stripped.startswith('"""')
        or stripped.startswith("'''")
    )


def find_id_usages_in_file(file_path: Path) -> List[Tuple[int, str, str]]:
    """Find all id= usages in Dash components.

    Returns:
        List of (line_number, matched_text, id_value) tuples.
    """
    violations = []

    with open(file_path, "r") as f:
        lines = f.readlines()

    # Common Dash component prefixes and callback patterns
    component_prefixes = [
        "html\\.",
        "dcc\\.",
        "dbc\\.",
        "dl\\.",
        "Input\\(",
        "Output\\(",
        "State\\(",
    ]

    # Track if we're inside a component definition (multi-line)
    in_component = False

    for line_num, line in enumerate(lines, start=1):
        # Skip comment lines
        if is_comment_or_docstring(line):
            continue

        # Skip lines with # nocheck comment
        if "# nocheck" in line or "#nocheck" in line:
            continue

        # Skip variable assignments (id = something with spaces around =)
        if re.search(r"\bid\s+=\s+", line):
            continue

        # Check if this line starts or continues a component
        has_component_start = any(
            re.search(prefix, line) for prefix in component_prefixes
        )

        # Start component context when we see a component prefix with opening paren
        if has_component_start and "(" in line:
            in_component = True

        # End component context when we see a closing paren at the start (dedented)
        if in_component and re.match(r"^\s*\)", line):
            in_component = False
            continue

        # Only check lines that are in a component context OR have a component prefix
        if not (in_component or has_component_start):
            continue

        # Now find id= patterns in this component line
        # Match: id="string", id='string', id=variable, id=f"string"
        # Use \b word boundary to match "id" as a word, not "job_id"
        patterns = [
            r'\bid\s*=\s*"([^"]+)"',  # id="string"
            r"\bid\s*=\s*'([^']+)'",  # id='string'
            r'\bid\s*=\s*f"([^"]+)"',  # id=f"string"
            r"\bid\s*=\s*f'([^']+)'",  # id=f'string'
            r"\bid\s*=\s*([a-z_][a-zA-Z0-9_]*)",  # id=variable  # noqa
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, line)
            for match in matches:
                id_value = match.group(1)
                matched_text = match.group(0)
                violations.append((line_num, matched_text, id_value))

    return violations


def find_non_constant_callback_ids(file_path: Path) -> List[Tuple[int, str, str]]:
    """Find Input/Output/State calls where the first arg is not an uppercase constant.

    Uses AST to detect string literals, function calls (e.g. hidden_id(...)),
    or any non-constant expression used as the component ID (first positional arg).

    Returns:
        List of (line_number, call_description, id_repr) tuples.
    """
    violations = []

    with open(file_path, "r") as f:
        source = f.read()
    lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Match Input(...), Output(...), State(...)
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in ("Input", "Output", "State")):
            continue

        # Must have at least one positional arg (the component ID)
        if not node.args:
            continue

        first_arg = node.args[0]

        # Check if the line has # nocheck
        line_idx = first_arg.lineno - 1
        if line_idx < len(lines) and (
            "# nocheck" in lines[line_idx] or "#nocheck" in lines[line_idx]
        ):
            continue

        # Acceptable: uppercase Name ending in _ID (constant from html_ids)
        if (
            isinstance(first_arg, ast.Name)
            and first_arg.id.isupper()
            and first_arg.id.endswith("_ID")
        ):
            continue

        # Everything else is a violation
        id_repr = ast.dump(first_arg)
        if isinstance(first_arg, ast.Constant):
            id_repr = repr(first_arg.value)
        elif isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Name):
            id_repr = f"{first_arg.func.id}(...)"

        call_desc = f"{func.id}({id_repr}, ...)"
        violations.append((first_arg.lineno, call_desc, id_repr))

    return violations


def check_if_constant_from_html_ids(
    id_value: str, html_ids_constants: Set[str]
) -> bool:
    """Check if an ID value is a constant from html_ids.py."""
    # Constant names are uppercase with underscores
    if not id_value.isupper():
        return False
    if not id_value.endswith("_ID"):
        return False
    return id_value in html_ids_constants


def _is_callback_call(node: ast.Call) -> bool:
    """Check if an ast.Call is a callback.

    Matches @app.callback, @callback, or dash.clientside_callback.
    """
    func = node.func
    # Pattern 1: @app.callback / dash.clientside_callback (ast.Attribute)
    if isinstance(func, ast.Attribute) and func.attr in (
        "callback",
        "clientside_callback",
    ):
        return True
    # Pattern 2: @callback (ast.Name)
    if isinstance(func, ast.Name) and func.id == "callback":
        return True
    return False


def _extract_callback_constants(call_node: ast.Call) -> Set[str]:
    """Extract ID constants from a callback call's arguments."""
    constants = set()
    for arg in call_node.args:
        constants.update(extract_constants_from_ast(arg))
    for keyword in call_node.keywords:
        constants.update(extract_constants_from_ast(keyword.value))
    return constants


def find_callback_id_usages_in_file(file_path: Path) -> Set[str]:
    """Find all ID constants used in callbacks.

    Detects three patterns:
    - @app.callback(...) decorators
    - @callback(...) decorators
    - dash.clientside_callback(...) top-level calls

    Returns:
        Set of constant names used in Input/Output/State.
    """
    used_constants = set()

    try:
        with open(file_path, "r") as f:
            content = f.read()

        tree = ast.parse(content, filename=str(file_path))

        # Pattern 1 & 2: @callback / @app.callback decorators on functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and _is_callback_call(decorator):
                        used_constants.update(_extract_callback_constants(decorator))

        # Pattern 3: dash.clientside_callback(...) top-level calls
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and _is_callback_call(node.value)
            ):
                used_constants.update(_extract_callback_constants(node.value))

    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in {file_path}: {e}") from e

    return used_constants


def extract_constants_from_ast(node: ast.AST) -> Set[str]:
    """Extract constant names from an AST node.

    Recursively searches for Name nodes that look like ID constants.
    """
    constants = set()

    if isinstance(node, ast.Name):
        # Check if this looks like an ID constant
        if node.id.isupper() and node.id.endswith("_ID"):
            constants.add(node.id)
    elif isinstance(node, ast.Call):
        # For Input(...), Output(...), State(...)
        # Check all arguments
        for arg in node.args:
            constants.update(extract_constants_from_ast(arg))
        for keyword in node.keywords:
            constants.update(extract_constants_from_ast(keyword.value))
    elif isinstance(node, ast.List) or isinstance(node, ast.Tuple):
        # Handle [Input(...), Output(...)]
        for element in node.elts:
            constants.update(extract_constants_from_ast(element))
    elif isinstance(node, ast.Dict):
        # Handle output={key: Output(...), ...} dict-style callbacks
        for value in node.values:
            constants.update(extract_constants_from_ast(value))

    return constants


def test_no_string_literal_ids():
    """Test that all id= usages use constants from html_ids.py."""
    src = get_src_path()
    html_ids_constants = set(load_html_ids_constants().keys())

    all_violations = []

    # Scan all Python files
    for py_file in find_python_files(src):
        # Skip html_ids.py itself
        if py_file.name == "html_ids.py":
            continue

        # Skip __pycache__ and similar
        if "__pycache__" in str(py_file):
            continue

        # Check id= keyword patterns (html/dcc/dbc components)
        violations = find_id_usages_in_file(py_file)
        for line_num, matched_text, id_value in violations:
            if not check_if_constant_from_html_ids(id_value, html_ids_constants):
                rel_path = py_file.relative_to(src.parent)
                all_violations.append(f"{rel_path}:{line_num} - {matched_text}")

        # Check first positional arg in Input/Output/State calls
        callback_violations = find_non_constant_callback_ids(py_file)
        for line_num, call_desc, id_repr in callback_violations:
            rel_path = py_file.relative_to(src.parent)
            all_violations.append(f"{rel_path}:{line_num} - {call_desc}")

    if all_violations:
        violations_str = "\n".join(f"  {v}" for v in all_violations)
        assert False, (
            "\n\nVIOLATIONS: Found id= usages with"
            " string literals or non-html_ids"
            f" constants:\n\n{violations_str}"
            "\n\nAll id= usages must use constants"
            " from constants/html_ids.py"
            "\nExample: id=MY_BUTTON_PAGE_ID"
            "\n\nAdd '# nocheck' to exclude a line."
        )


def test_no_unused_id_constants():
    """Test that all constants in html_ids.py are used in callbacks."""
    src = get_src_path()
    html_ids_constants = load_html_ids_constants()

    # Find all constants used in callbacks across all files
    used_in_callbacks = set()
    for py_file in find_python_files(src):
        if "__pycache__" in str(py_file):
            continue
        used_in_callbacks.update(find_callback_id_usages_in_file(py_file))

    # Check for unused constants
    violations = []
    for const_name, has_nocheck in html_ids_constants.items():
        if const_name not in used_in_callbacks:
            if not has_nocheck:
                violations.append(const_name)

    if violations:
        violations_str = "\n".join(f"  {v}" for v in sorted(violations))
        assert False, (
            "\n\nVIOLATIONS: Found ID constants not"
            " used in any @app.callback"
            f" decorator:\n\n{violations_str}"
            "\n\nEither:"
            "\n  1. Use it in a callback, OR"
            "\n  2. Add '# nocheck' to html_ids.py"
        )
