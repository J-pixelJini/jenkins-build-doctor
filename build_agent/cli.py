"""
Command-line entrypoint.

Usage:
    # Diagnose the last failed build of a job
    python -m build_agent.cli diagnose --job my-service

    # Diagnose a specific build number
    python -m build_agent.cli diagnose --job my-service --build 482

    # Diagnose + immediately re-trigger the job if a fix is expected upstream
    python -m build_agent.cli diagnose --job my-service --rebuild

    # Just re-trigger, no diagnosis
    python -m build_agent.cli rebuild --job my-service

    # Try it with no Jenkins server at all, against a bundled sample log
    python -m build_agent.cli demo --fixture tests/fixtures/maven_test_failure.log
"""

from __future__ import annotations

import argparse
import sys

from .diagnoser import diagnose
from .jenkins_client import JenkinsClient, JenkinsClientError, JenkinsConfig


def _cmd_diagnose(args: argparse.Namespace) -> int:
    try:
        config = JenkinsConfig.from_env()
    except JenkinsClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    client = JenkinsClient(config)
    build_number = args.build or "lastFailedBuild"
    if build_number == "lastFailedBuild":
        try:
            build_number = client.last_failed_build_number(args.job)
        except JenkinsClientError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    print(f"Fetching console log for {args.job} #{build_number} ...")
    log_text = client.console_log(args.job, build_number)
    result = diagnose(log_text)
    print()
    print(result)

    if args.rebuild:
        print()
        print(f"Re-triggering {args.job} ...")
        queue_url = client.trigger_build(args.job)
        new_build = client.wait_for_queued_build_number(queue_url)
        if new_build:
            print(f"New build started: {args.job} #{new_build}")
        else:
            print("Build queued (still waiting for an executor, or Jenkins didn't confirm in time).")
    return 0


def _cmd_rebuild(args: argparse.Namespace) -> int:
    try:
        config = JenkinsConfig.from_env()
    except JenkinsClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    client = JenkinsClient(config)
    queue_url = client.trigger_build(args.job)
    new_build = client.wait_for_queued_build_number(queue_url)
    if new_build:
        print(f"New build started: {args.job} #{new_build}")
    else:
        print("Build queued.")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    with open(args.fixture, "r", encoding="utf-8") as f:
        log_text = f.read()
    result = diagnose(log_text)
    print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-doctor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Diagnose why a build failed")
    p_diag.add_argument("--job", required=True, help="Jenkins job name")
    p_diag.add_argument("--build", default=None, help="Build number (default: last failed build)")
    p_diag.add_argument("--rebuild", action="store_true", help="Re-trigger the job after diagnosing")
    p_diag.set_defaults(func=_cmd_diagnose)

    p_rebuild = sub.add_parser("rebuild", help="Re-trigger a job without diagnosing")
    p_rebuild.add_argument("--job", required=True, help="Jenkins job name")
    p_rebuild.set_defaults(func=_cmd_rebuild)

    p_demo = sub.add_parser("demo", help="Run diagnosis against a local log file, no Jenkins needed")
    p_demo.add_argument("--fixture", required=True, help="Path to a console log text file")
    p_demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
