import pytest

from agent.test_utils import validate_pytest_code


def test_accepts_simple_pytest_function():

    code = (
        "def test_truth():\n"
        "    assert True\n"
    )

    assert "test_truth" in validate_pytest_code(code)


def test_rejects_invalid_python():

    with pytest.raises(
        ValueError,
        match="syntax error"
    ):
        validate_pytest_code(
            "def test_bad(\n"
        )


def test_rejects_non_tests():

    with pytest.raises(
        ValueError,
        match="test_ function"
    ):
        validate_pytest_code(
            "x = 3"
        )