# jenkins-build-doctor

A small CLI agent that looks at a **failed Jenkins build**, figures out *why*
it failed from the console log, and — if you want — re-triggers the job.

## Why

CI failures usually fall into a handful of recurring buckets (a flaky/broken
test, a dependency that can't resolve, a compile error, the runner ran out of
memory, a step timed out, an auth/permission problem). Scrolling a 2,000-line
console log to find which bucket you're in is repetitive. This tool reads the
log, matches it against a set of known failure signatures, and prints a short
diagnosis with the relevant log lines as evidence — then optionally kicks off
a rebuild for you.

## How it works

- `build_agent/jenkins_client.py` — thin wrapper over the Jenkins REST API
  (fetch a build's console log, find the last failed build, trigger a new
  build, poll the build queue for the resulting build number). Auth is an API
  token read from environment variables, never hardcoded.
- `build_agent/diagnoser.py` — the actual "why did it fail" logic. An ordered
  list of regex signatures (test failure, dependency resolution error, compile
  error, OOM, timeout, permission/auth error), each producing a short summary
  plus the specific log lines that justify it. Falls back to a generic
  "unclassified — here are the ERROR lines" diagnosis if nothing matches.
- `build_agent/cli.py` — the command-line entrypoint tying the two together.

## Try it without a Jenkins server

The `demo` command runs the diagnoser against a bundled sample log, so you can
see it work with zero setup:

```bash
pip install -r requirements.txt
python -m build_agent.cli demo --fixture tests/fixtures/maven_test_failure.log
python -m build_agent.cli demo --fixture tests/fixtures/npm_dependency_error.log
python -m build_agent.cli demo --fixture tests/fixtures/timeout.log
python -m build_agent.cli demo --fixture tests/fixtures/oom.log
python -m build_agent.cli demo --fixture tests/fixtures/generic_error.log
```

## Use it against a real Jenkins instance

```bash
export JENKINS_URL="https://your-jenkins-host"
export JENKINS_USER="your-username"
export JENKINS_API_TOKEN="your-api-token"   # Jenkins > your user > Configure > API Token — never your password

# Diagnose the last failed build of a job
python -m build_agent.cli diagnose --job my-service

# Diagnose a specific build number
python -m build_agent.cli diagnose --job my-service --build 482

# Diagnose, then re-trigger the same job
python -m build_agent.cli diagnose --job my-service --rebuild

# Just re-trigger, skip diagnosis
python -m build_agent.cli rebuild --job my-service
```

## Tests

```bash
python -m pytest tests/ -v
```

9 tests cover each failure category against a real sample log fixture, plus
edge cases (empty log, readable string formatting).

## Extending it

Add a new failure type by adding one `_Signature(category, regex_pattern,
summarize_fn)` entry to `_SIGNATURES` in `diagnoser.py` and a fixture log
under `tests/fixtures/` to test it against. Order matters — more specific
signatures should be listed before more generic ones, since the first match
wins.

## Tech stack

Python 3.11, `requests` for the Jenkins REST API, `pytest` for tests. No
external services required to run the test suite or the demo mode.
