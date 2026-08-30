"""
Classifies *why* a Jenkins build failed from its console log text.

Approach: an ordered list of failure signatures. Each signature is checked
in turn (order matters — more specific signatures are checked before the
generic catch-all), and the first match wins. This is a simple, explainable
heuristic rather than an ML classifier on purpose: build logs are
semi-structured text with well-known failure vocabularies (Maven, npm,
pytest, JVM, shell), so regex signatures cover the common cases cheaply and
the reasoning behind any given diagnosis is easy to inspect and extend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Diagnosis:
    category: str
    summary: str
    evidence: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"[{self.category}] {self.summary}"]
        for line in self.evidence:
            lines.append(f"    > {line}")
        return "\n".join(lines)


@dataclass
class _Signature:
    category: str
    pattern: re.Pattern
    summarize: "callable"


def _maven_test_failures(log: str, match: re.Match) -> Diagnosis:
    # Matches e.g. "[ERROR] com.acme.payments.RefundServiceTest.shouldRejectRefund() FAILED"
    # or a bare "some.pkg.TestClass.methodName FAILED" without the trailing parens.
    failing_tests = re.findall(r"^\s*(?:\[ERROR\]\s*)?([\w.$]+(?:\(\))?)\s+FAILED\s*$", log, re.MULTILINE)
    evidence = list(dict.fromkeys(failing_tests))[:5] or [match.group(0)]
    count_match = re.search(
        r"Tests run: (\d+), Failures: (\d+), Errors: (\d+)", log
    )
    summary = "One or more unit tests failed."
    if count_match:
        run, fails, errs = count_match.groups()
        summary = f"{fails} test failure(s) and {errs} error(s) out of {run} tests run."
    return Diagnosis("test_failure", summary, evidence)


def _npm_dependency_error(log: str, match: re.Match) -> Diagnosis:
    lines = [l for l in log.splitlines() if "npm ERR!" in l][:6]
    return Diagnosis(
        "dependency_error",
        "npm could not resolve or install a package dependency.",
        lines or [match.group(0)],
    )


def _pip_dependency_error(log: str, match: re.Match) -> Diagnosis:
    lines = [
        l for l in log.splitlines()
        if "ERROR: " in l or "Could not find a version" in l
    ][:6]
    return Diagnosis(
        "dependency_error",
        "pip could not resolve or install a Python package dependency.",
        lines or [match.group(0)],
    )


def _compile_error(log: str, match: re.Match) -> Diagnosis:
    lines = [
        l for l in log.splitlines()
        if re.search(r"error:|cannot find symbol|syntax error", l, re.IGNORECASE)
    ][:6]
    return Diagnosis(
        "compile_error",
        "The build failed to compile.",
        lines or [match.group(0)],
    )


def _oom(log: str, match: re.Match) -> Diagnosis:
    return Diagnosis(
        "out_of_memory",
        "The build process ran out of memory.",
        [match.group(0)],
    )


def _timeout(log: str, match: re.Match) -> Diagnosis:
    return Diagnosis(
        "timeout",
        "The build was aborted for exceeding its time limit.",
        [match.group(0)],
    )


def _permission_or_auth(log: str, match: re.Match) -> Diagnosis:
    return Diagnosis(
        "permission_or_auth",
        "The build failed due to a permission or authentication error "
        "(e.g. bad credentials, denied access to a registry or repo).",
        [match.group(0)],
    )


def _generic_failure(log: str, match: re.Match) -> Diagnosis:
    error_lines = [l for l in log.splitlines() if "ERROR" in l.upper()][-6:]
    return Diagnosis(
        "unclassified",
        "Build failed (no known signature matched); showing the last "
        "ERROR-containing lines for manual triage.",
        error_lines or ["(no ERROR lines found — inspect full log)"],
    )


_SIGNATURES: list[_Signature] = [
    _Signature("test_failure", re.compile(r"Tests run:.*Failures: [1-9]|<<< FAILURE!"), _maven_test_failures),
    _Signature("test_failure", re.compile(r"^FAILED\s+\S+::", re.MULTILINE), _maven_test_failures),
    _Signature("dependency_error", re.compile(r"npm ERR! code E"), _npm_dependency_error),
    _Signature("dependency_error", re.compile(r"Could not find a version that satisfies|ERROR: Could not install packages"), _pip_dependency_error),
    _Signature("compile_error", re.compile(r"BUILD FAILURE.*\n.*Compilation failure|cannot find symbol", re.DOTALL), _compile_error),
    _Signature("out_of_memory", re.compile(r"OutOfMemoryError|Java heap space"), _oom),
    _Signature("timeout", re.compile(r"Build timed out|Timeout waiting", re.IGNORECASE), _timeout),
    _Signature("permission_or_auth", re.compile(r"403 Forbidden|401 Unauthorized|Permission denied \(publickey\)|bad credentials", re.IGNORECASE), _permission_or_auth),
]


def diagnose(log_text: str) -> Diagnosis:
    """Runs every signature against the log and returns the first match,
    falling back to a generic diagnosis if nothing recognized fires."""
    for sig in _SIGNATURES:
        match = sig.pattern.search(log_text)
        if match:
            return sig.summarize(log_text, match)
    return _generic_failure(log_text, re.match(r"", ""))
