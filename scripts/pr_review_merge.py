#!/usr/bin/env python3
"""Merge approved pull requests after review-thread and check gates pass."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import subprocess
import sys
import time
from typing import Any, Protocol


MERGEABLE_STATES = {"CLEAN", "HAS_HOOKS", "UNSTABLE"}
PASSING_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILING_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PENDING_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}


class Runner(Protocol):
    def run_json(self, args: list[str]) -> Any:
        """Run a gh command and parse JSON output."""

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a gh command."""


class GhRunner:
    def run_json(self, args: list[str]) -> Any:
        completed = self.run(args)
        if not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
        )


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    head_sha: str
    is_draft: bool
    merge_state: str
    review_decision: str | None
    status_rollup: list[dict[str, Any]]


@dataclass(frozen=True)
class Decision:
    should_merge: bool
    reasons: list[str]


def parse_repo(repo: str) -> tuple[str, str]:
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("--repo must be in OWNER/NAME form")
    return parts[0], parts[1]


def list_open_pr_numbers(runner: Runner, repo: str) -> list[int]:
    payload = runner.run_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number",
        ]
    )
    return [item["number"] for item in payload or []]


def load_pr(runner: Runner, repo: str, number: int) -> PullRequest:
    payload = runner.run_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            (
                "number,title,headRefOid,isDraft,mergeStateStatus,"
                "reviewDecision,statusCheckRollup"
            ),
        ]
    )
    return PullRequest(
        number=payload["number"],
        title=payload["title"],
        head_sha=payload["headRefOid"],
        is_draft=bool(payload["isDraft"]),
        merge_state=payload.get("mergeStateStatus") or "UNKNOWN",
        review_decision=payload.get("reviewDecision"),
        status_rollup=payload.get("statusCheckRollup") or [],
    )


def unresolved_review_thread_count(runner: Runner, repo: str, number: int) -> int:
    owner, name = parse_repo(repo)
    payload = runner.run_json(
        [
            "api",
            "graphql",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
            "-f",
            "query="
            "query($owner:String!,$name:String!,$number:Int!){"
            " repository(owner:$owner,name:$name){"
            "  pullRequest(number:$number){"
            "   reviewThreads(first:100){"
            "    nodes{isResolved isOutdated}"
            "   }"
            "  }"
            " }"
            "}",
        ]
    )
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    return sum(
        1
        for node in nodes
        if not node.get("isResolved") and not node.get("isOutdated")
    )


def check_blockers(status_rollup: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for item in status_rollup:
        name = item.get("name") or item.get("context") or item.get("workflowName") or "check"
        state = str(item.get("state") or item.get("status") or "").upper()
        conclusion = str(item.get("conclusion") or "").upper()

        if conclusion in FAILING_STATES or state in FAILING_STATES:
            blockers.append(f"{name} is failing")
            continue
        if state in PENDING_STATES:
            blockers.append(f"{name} is pending")
            continue
        if conclusion and conclusion not in PASSING_STATES:
            blockers.append(f"{name} conclusion is {conclusion}")
            continue
        if state and state not in PASSING_STATES and state != "COMPLETED":
            blockers.append(f"{name} state is {state}")
    return blockers


def decide(pr: PullRequest, unresolved_threads: int, *, require_approval: bool) -> Decision:
    reasons: list[str] = []
    if pr.is_draft:
        reasons.append("draft PR")
    if unresolved_threads:
        reasons.append(f"{unresolved_threads} unresolved review thread(s)")
    if require_approval and pr.review_decision != "APPROVED":
        reasons.append(f"review decision is {pr.review_decision or 'missing'}")
    if pr.merge_state not in MERGEABLE_STATES:
        reasons.append(f"merge state is {pr.merge_state}")
    reasons.extend(check_blockers(pr.status_rollup))
    return Decision(should_merge=not reasons, reasons=reasons)


def auto_approval_blockers(pr: PullRequest, unresolved_threads: int) -> list[str]:
    reasons: list[str] = []
    if pr.is_draft:
        reasons.append("draft PR")
    if unresolved_threads:
        reasons.append(f"{unresolved_threads} unresolved review thread(s)")
    if pr.merge_state not in MERGEABLE_STATES and not (
        pr.merge_state == "BLOCKED" and pr.review_decision != "APPROVED"
    ):
        reasons.append(f"merge state is {pr.merge_state}")
    reasons.extend(check_blockers(pr.status_rollup))
    return reasons


def approve_pr(runner: Runner, repo: str, pr: PullRequest) -> None:
    runner.run(
        [
            "pr",
            "review",
            str(pr.number),
            "--repo",
            repo,
            "--approve",
            "--body",
            (
                "Automated approval: checks passed, review threads are resolved, "
                "and the scheduled PR merge gate found no non-review blockers."
            ),
        ]
    )


def wait_for_pr_refresh(
    runner: Runner,
    repo: str,
    number: int,
    *,
    attempts: int = 3,
    delay_seconds: int = 2,
) -> PullRequest:
    pr = load_pr(runner, repo, number)
    for _ in range(1, attempts):
        if pr.review_decision == "APPROVED":
            return pr
        time.sleep(delay_seconds)
        pr = load_pr(runner, repo, number)
    return pr


def merge_pr(runner: Runner, repo: str, pr: PullRequest) -> None:
    runner.run(
        [
            "pr",
            "merge",
            str(pr.number),
            "--repo",
            repo,
            "--merge",
            "--match-head-commit",
            pr.head_sha,
        ]
    )


def load_pr_merge_result(runner: Runner, repo: str, number: int) -> dict[str, Any]:
    payload = runner.run_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "state,mergedAt,mergeCommit",
        ]
    )
    return payload or {}


def merge_commit_oid(payload: dict[str, Any]) -> str:
    merge_commit = payload.get("mergeCommit") or {}
    return merge_commit.get("oid") or "unknown merge commit"


def is_merged(payload: dict[str, Any]) -> bool:
    return payload.get("state") == "MERGED" or bool(payload.get("mergedAt"))


def process_queue(
    runner: Runner,
    repo: str,
    *,
    merge: bool,
    require_approval: bool,
    auto_approve: bool = False,
) -> int:
    numbers = list_open_pr_numbers(runner, repo)
    if not numbers:
        print("No open pull requests.")
        return 0

    merged = 0
    for number in numbers:
        pr = load_pr(runner, repo, number)
        unresolved_threads = unresolved_review_thread_count(runner, repo, number)

        if merge and auto_approve and require_approval and pr.review_decision != "APPROVED":
            blockers = auto_approval_blockers(pr, unresolved_threads)
            if blockers:
                print(f"PR #{pr.number} not auto-approved: {', '.join(blockers)}")
            else:
                try:
                    approve_pr(runner, repo, pr)
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or str(exc)).strip()
                    print(f"PR #{pr.number} auto-approval failed: {detail}")
                else:
                    print(f"PR #{pr.number} approved at {pr.head_sha}.")
                    pr = wait_for_pr_refresh(runner, repo, pr.number)

        decision = decide(pr, unresolved_threads, require_approval=require_approval)

        if not decision.should_merge:
            print(f"PR #{pr.number} skipped: {', '.join(decision.reasons)}")
            continue

        if merge:
            try:
                merge_pr(runner, repo, pr)
            except subprocess.CalledProcessError:
                merge_result = load_pr_merge_result(runner, repo, pr.number)
                if not is_merged(merge_result):
                    raise
                print(f"PR #{pr.number} already merged at {merge_commit_oid(merge_result)}.")
            else:
                print(f"PR #{pr.number} merged at {pr.head_sha}.")
            merged += 1
        else:
            print(f"PR #{pr.number} ready to merge at {pr.head_sha}.")
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--repo", required=True, help="Repository in OWNER/NAME form.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--merge", action="store_true", help="Merge ready PRs.")
    mode.add_argument("--dry-run", action="store_true", help="Report only; do not merge.")
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require reviewDecision=APPROVED before merging.",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Approve PRs that have no non-review blockers before merging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parse_repo(args.repo)
        process_queue(
            GhRunner(),
            args.repo,
            merge=args.merge and not args.dry_run,
            require_approval=args.require_approval,
            auto_approve=args.auto_approve,
        )
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
