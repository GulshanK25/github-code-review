"""Static checks for LLM-generated pytest. No generated code runs here.

These checks catch common mistakes but are NOT a security sandbox or proof of
correctness. Actual execution is optional and restricted to Docker.
"""

import ast
from pathlib import PurePosixPath

BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "requests", "urllib", "http",
    "shutil", "ctypes", "multiprocessing", "importlib", "pickle",
}
BLOCKED_CALLS = {"eval", "exec", "compile", "open", "__import__", "input"}


def validate_pytest_code(code: str) -> str:
    """Keep the old API; raise on invalid Python or missing test functions."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("The AI did not produce pytest code.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Generated pytest code contains a syntax error: {exc}") from exc
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in tree.body
    ):
        raise ValueError("Generated code does not contain a top-level test_ function.")
    return code


def inspect_generated_tests(code: str, sources: list[dict[str, str]]) -> list[str]:
    """Return actionable feedback for the LLM; no Python code is executed."""
    try:
        validate_pytest_code(code)
        tree = ast.parse(code)
    except ValueError as exc:
        return [str(exc)]

    problems: list[str] = []
    imported: set[str] = set()
    tests: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    seen: set[str] = set()

    # Match source functions to importable module names relative to --repo.
    functions: dict[str, set[str]] = {}
    for source in sources:
        path = PurePosixPath(source["path"])
        module_name = ".".join(path.with_suffix("").parts)
        if path.name == "__init__.py":
            module_name = ".".join(path.parent.parts)
        try:
            source_ast = ast.parse(source["content"])
        except SyntaxError:
            continue
        functions[module_name] = {
            node.name for node in source_ast.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
                if alias.name.split(".")[0] in BLOCKED_IMPORTS:
                    problems.append(f"Forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in BLOCKED_IMPORTS:
                problems.append(f"Forbidden import from: {node.module}")
            for alias in node.names:
                imported.add(alias.asname or alias.name)
                if alias.name in set().union(*functions.values()) and node.module not in functions:
                    problems.append(
                        f"Import '{alias.name}' from '{node.module}' is not available "
                        f"in the selected --repo source root; use {list(functions)}."
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            tests.append(node)

    # Detect missing imports of known functions from the provided source files.
    known_functions = set().union(*functions.values()) if functions else set()
    names_at_module = imported | {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for name in sorted(known_functions):
        referenced = any(
            isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name
            for test in tests for node in ast.walk(test)
        )
        if referenced and name not in names_at_module:
            modules = [module for module, exported in functions.items() if name in exported]
            problems.append(f"Missing import for '{name}'. Example: from {modules[0]} import {name}")

    for test in tests:
        signature = ast.dump(ast.Module(body=test.decorator_list + test.body, type_ignores=[]))
        if signature in seen:
            problems.append(f"'{test.name}' duplicates another test's decorators and body")
        seen.add(signature)
        assertions = [n for n in ast.walk(test) if isinstance(n, ast.Assert)]
        if not assertions:
            problems.append(
                f"'{test.name}' needs a meaningful assert. "
                "If this test only uses pytest.raises for an undocumented input "
                "type, remove that test. Never add 'assert True' to bypass validation."
            )
        elif all(isinstance(n.test, ast.Constant) for n in assertions):
            problems.append(
                f"'{test.name}' contains only constant assertions; "
                "assert a documented function result instead."
            )

    # A parametrized function's arguments are ordinary values, not fixtures.
    # In particular, indirect="expected" is interpreted by pytest as individual
    # fixture names ('e', 'x', ...), leading to a collection error.
    for test in tests:
        parameter_names = {
            item.arg
            for item in test.args.posonlyargs + test.args.args + test.args.kwonlyargs
        }
        for decorator in test.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"
                and isinstance(decorator.func.value, ast.Attribute)
                and decorator.func.value.attr == "mark"
                and isinstance(decorator.func.value.value, ast.Name)
                and decorator.func.value.value.id == "pytest"
            ):
                continue

            for keyword in decorator.keywords:
                if keyword.arg == "indirect" and not (
                    isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                ):
                    problems.append(
                        f"'{test.name}': remove indirect= from pytest.mark.parametrize. "
                        "These are ordinary function arguments, not pytest fixtures. "
                        "Using indirect='expected' can trigger "
                        "indirect fixture 'e' doesn't exist."
                    )

            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                spec = decorator.args[0].value
                if isinstance(spec, str):
                    requested = [name.strip() for name in spec.split(",") if name.strip()]
                    unknown = [name for name in requested if name not in parameter_names]
                    if unknown:
                        problems.append(
                            f"'{test.name}': parametrize names {unknown} do not "
                            "match function arguments."
                        )
                    if len(requested) != len(set(requested)):
                        problems.append(
                            f"'{test.name}': duplicate parameter names in parametrize."
                        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Set) and any(
            isinstance(item, ast.Dict) for item in node.elts
        ):
            problems.append(
                "Set literal contains a dictionary. "
                "Use {'role': 'admin'} instead of {{'role': 'admin'}}. "
                "Double braces cause TypeError during pytest collection."
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                problems.append(f"Forbidden call: {node.func.id}()")
            # Generic exception assertions hide a wrong test contract.
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "raises"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest"
                    and node.args and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in {"Exception", "BaseException"}):
                problems.append("Avoid pytest.raises(Exception); assert the documented behavior instead")

    return list(dict.fromkeys(problems))
