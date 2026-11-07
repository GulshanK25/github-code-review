"""Regression tests for misleading exception-only generated tests."""
from agent.test_utils import inspect_generated_tests


def source():
    return [{"path": "auth.py", "content": "def can_delete_account(user):\n    return bool(user)\n"}]


def test_undocumented_exception_only_test_gives_repair_feedback():
    code = (
        "import pytest\nfrom auth import can_delete_account\n"
        "def test_non_dict():\n"
        "    with pytest.raises(TypeError):\n"
        "        can_delete_account('someone')\n"
    )
    errors = inspect_generated_tests(code, source())
    assert any("remove that test" in error.lower() for error in errors)


def test_tautology_rejected():
    code = "def test_empty():\n    assert True\n"
    errors = inspect_generated_tests(code, [])
    assert any("constant assertions" in error for error in errors)


def test_role_regression_is_accepted():
    code = (
        "from auth import can_delete_account\n"
        "def test_non_admin():\n"
        "    assert can_delete_account({'role': 'user'}) is False\n"
    )
    assert inspect_generated_tests(code, source()) == []


def test_indirect_fixture_error_detected():
    code = (
        "import pytest\nfrom auth import can_delete_account\n"
        "@pytest.mark.parametrize('user, expected', "
        "[({'role': 'admin'}, True), ({'role': 'user'}, False)], "
        "indirect='expected')\n"
        "def test_permissions(user, expected):\n"
        "    assert can_delete_account(user) is expected\n"
    )
    problems = inspect_generated_tests(code, source())
    assert any("remove indirect=" in item for item in problems)


def test_normal_parametrize_accepted():
    code = (
        "import pytest\nfrom auth import can_delete_account\n"
        "@pytest.mark.parametrize('user, expected', "
        "[({'role': 'admin'}, True), ({'role': 'user'}, False)])\n"
        "def test_permissions(user, expected):\n"
        "    assert can_delete_account(user) is expected\n"
    )
    assert inspect_generated_tests(code, source()) == []


def test_bad_parametrize_argument_name_detected():
    code = (
        "import pytest\nfrom auth import can_delete_account\n"
        "@pytest.mark.parametrize('user, e', [({'role': 'admin'}, True)])\n"
        "def test_permissions(user, expected):\n"
        "    assert can_delete_account(user) is expected\n"
    )
    problems = inspect_generated_tests(code, source())
    assert any("do not match function arguments" in item for item in problems)


def test_double_brace_dictionary_is_rejected():
    code = (
        "import pytest\nfrom auth import can_delete_account\n"
        "@pytest.mark.parametrize('user', [{{'role': 'admin'}}])\n"
        "def test_permissions(user):\n"
        "    assert can_delete_account(user) is True\n"
    )
    problems = inspect_generated_tests(code, source())
    assert any("Set literal contains a dictionary" in item for item in problems)
