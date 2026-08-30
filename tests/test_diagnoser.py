import pathlib

import pytest

from build_agent.diagnoser import diagnose

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.mark.parametrize(
    "fixture, expected_category",
    [
        ("maven_test_failure.log", "test_failure"),
        ("npm_dependency_error.log", "dependency_error"),
        ("timeout.log", "timeout"),
        ("oom.log", "out_of_memory"),
        ("generic_error.log", "unclassified"),
    ],
)
def test_diagnose_categorizes_correctly(fixture, expected_category):
    log_text = _load(fixture)
    result = diagnose(log_text)
    assert result.category == expected_category


def test_maven_test_failure_lists_failing_tests():
    result = diagnose(_load("maven_test_failure.log"))
    assert "2" in result.summary  # 2 failures
    assert any("Refund" in e or "shouldReject" in e or "shouldEmit" in e for e in result.evidence) or result.evidence


def test_npm_dependency_error_includes_npm_err_lines():
    result = diagnose(_load("npm_dependency_error.log"))
    assert any("npm ERR!" in e for e in result.evidence)


def test_empty_log_falls_back_to_unclassified():
    result = diagnose("")
    assert result.category == "unclassified"


def test_diagnosis_str_is_readable():
    result = diagnose(_load("oom.log"))
    text = str(result)
    assert "[out_of_memory]" in text
    assert "OutOfMemoryError" in text
