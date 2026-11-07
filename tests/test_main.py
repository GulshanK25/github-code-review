"""Verify that generated tests are saved but never automatically run."""

import sys

import main


class FakeGraph:

    def invoke(self, state):

        assert state["generate_tests"] is True

        return {
            "report": "# Fake review\n",
            "test_plan": {
                "pytest_code": (
                    "def test_proposal():\n"
                    "    assert True\n"
                )
            },
        }


def test_generated_file_is_saved_not_run(
    tmp_path,
    monkeypatch
):

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        main,
        "build_graph",
        lambda: FakeGraph()
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--generate-tests"]
    )

    main.main()

    assert (
        tmp_path / "generated_tests" / "test_ai_generated.py"
    ).read_text() == (
        "def test_proposal():\n"
        "    assert True\n"
    )

    assert (
        tmp_path / "review_report.md"
    ).read_text() == "# Fake review\n"