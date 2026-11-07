"""Validate proposed test code without executing it."""

import ast


def validate_pytest_code(code: str) -> str:

    """
    Check Python syntax and presence of test functions.

    This does not guarantee correctness or security.
    """

    if not isinstance(code, str) or not code.strip():
        raise ValueError(
            "The AI did not produce any pytest code."
        )

    try:
        tree = ast.parse(code)

    except SyntaxError as exc:
        raise ValueError(
            f"Generated pytest code contains a syntax error: {exc}"
        ) from exc

    if not any(
        isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.name.startswith("test_")
        for node in ast.walk(tree)
    ):
        raise ValueError(
            "Generated code does not contain a test_ function."
        )

    return code