"""Load explicitly specified boolean behavior requirements without executing them."""

import ast
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

MAX_CONTRACT_BYTES = 16_000
_IDENTIFIER = r"[A-Za-z_][A-Za-z_0-9]*"
_MODULE_PATTERN = rf"{_IDENTIFIER}(?:\.{_IDENTIFIER})*"


class ContractCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    input: dict[str, object]
    expected: StrictBool


class BehaviorContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str = Field(pattern=rf"^{_MODULE_PATTERN}$")
    function: str = Field(pattern=rf"^{_IDENTIFIER}$")
    description: str = Field(min_length=1, max_length=1000)
    test_cases: list[ContractCase] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_names(self):
        names = [case.name for case in self.test_cases]
        if len(names) != len(set(names)):
            raise ValueError("Contract test case names must be unique")
        return self


def load_behavior_contract(
    repo: str | Path,
    contract_path: str | None = None,
    sources: list[dict[str, str]] | None = None,
) -> dict | None:
    """Discover contract at --repo/behavior_contract.json unless overridden.

    An explicit contract must remain within the chosen source root. Missing
    implicit contracts are okay, to preserve earlier runs without contracts.
    """
    root = Path(repo).resolve()
    if contract_path:
        provided = Path(contract_path)
        # Accept either a path relative to the current directory or --repo.
        candidate = provided if provided.is_absolute() or provided.exists() else root / provided
    else:
        candidate = root / "behavior_contract.json"

    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Behavior contract must be inside --repo")
    if not candidate.is_file():
        if contract_path:
            raise FileNotFoundError(f"Behavior contract not found: {candidate}")
        return None
    if candidate.stat().st_size > MAX_CONTRACT_BYTES:
        raise ValueError("Behavior contract is too large")

    try:
        contract = BehaviorContract.model_validate_json(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid behavior contract at {candidate}: {exc}") from exc

    # If we have changed source files, do not silently use a contract for an
    # unrelated module/function. This is a common cause of misleading tests.
    if sources:
        module_file = contract.module.replace(".", "/") + ".py"
        matches = [src for src in sources if src["path"] == module_file]
        if not matches:
            raise ValueError(
                f"Contract module '{contract.module}' is not among the changed source files"
            )
        try:
            tree = ast.parse(matches[0]["content"])
        except SyntaxError as exc:
            raise ValueError("Changed source file cannot be parsed") from exc
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == contract.function for node in tree.body
        ):
            raise ValueError(f"Function '{contract.function}' not found in {module_file}")

    return contract.model_dump()


def contract_pytest_code(contract: dict) -> str:
    """Build independent pytest checks directly from JSON requirements.

    This is run only inside the Docker sandbox, not with local host pytest.
    The JSON schema restricts import names to Python identifiers; inputs are
    emitted as Python literal values, never evaluated as code strings.
    """
    validated = BehaviorContract.model_validate(contract)
    cases = ",\n".join(
        f"    ({case.input!r}, {case.expected!r})" for case in validated.test_cases
    )
    ids = ", ".join(repr(case.name) for case in validated.test_cases)
    return (
        "import pytest\n"
        f"from {validated.module} import {validated.function} as _contract_subject\n\n"
        "@pytest.mark.parametrize('user_input, expected', [\n"
        + cases + "\n], ids=[" + ids + "])\n"
        "def test_behavior_contract(user_input, expected):\n"
        "    assert _contract_subject(user_input) is expected\n"
    )
