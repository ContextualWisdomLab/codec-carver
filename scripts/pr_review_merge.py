#!/usr/bin/env python3
"""Merge approved pull requests after review-thread and check gates pass."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import subprocess
import sys
import time
from typing import Any, Protocol


MERGEABLE_STATES = {"CLEAN", "HAS_HOOKS", "UNSTABLE"}
PASSING_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILING_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PENDING_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
DISPATCH_MARKER = "<!-- scheduled-pr-review-merge opencode-dispatch"


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
            shell=False,
        )


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    base_ref: str
    base_sha: str
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
                "reviewDecision,statusCheckRollup,baseRefName,baseRefOid"
            ),
        ]
    )
    return PullRequest(
        number=payload["number"],
        title=payload["title"],
        base_ref=payload["baseRefName"],
        base_sha=payload["baseRefOid"],
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


def authenticated_login(runner: Runner) -> str:
    try:
        payload = runner.run_json(["api", "user"])
    except subprocess.CalledProcessError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("login") or "")


def review_mentions_head(body: str, head_sha: str) -> bool:
    return (
        head_sha in body
        or f"Head SHA: `{head_sha}`" in body
        or f"head_sha={head_sha}" in body
    )


def current_opencode_review_exists(runner: Runner, repo: str, pr: PullRequest) -> bool:
    pages = runner.run_json(
        ["api", f"repos/{repo}/pulls/{pr.number}/reviews", "--paginate", "--slurp"]
    )
    for page in pages or []:
        for review in page or []:
            state = str(review.get("state") or "").upper()
            if state not in {"APPROVED", "CHANGES_REQUESTED"}:
                continue
            login = str((review.get("user") or {}).get("login") or "").lower()
            body = str(review.get("body") or "")
            commit_id = str(review.get("commit_id") or "")
            if "opencode" not in login and "OpenCode Agent" not in body:
                continue
            if commit_id == pr.head_sha or review_mentions_head(body, pr.head_sha):
                return True
    return False


def opencode_check_is_pending(status_rollup: list[dict[str, Any]]) -> bool:
    for item in status_rollup:
        name = " ".join(
            str(value or "")
            for value in (
                item.get("name"),
                item.get("context"),
                item.get("workflowName"),
                ((item.get("checkSuite") or {}).get("workflowRun") or {})
                .get("workflow", {})
                .get("name"),
            )
        ).lower()
        if "opencode" not in name:
            continue
        state = str(item.get("state") or item.get("status") or "").upper()
        if state in PENDING_STATES:
            return True
    return False


def recent_dispatch_marker_exists(
    runner: Runner,
    repo: str,
    pr: PullRequest,
    *,
    retry_seconds: int,
) -> bool:
    pages = runner.run_json(
        ["api", f"repos/{repo}/issues/{pr.number}/comments", "--paginate", "--slurp"]
    )
    marker_re = re.compile(
        r"<!-- scheduled-pr-review-merge opencode-dispatch "
        r"head_sha=([0-9a-fA-F]{40}) epoch=([0-9]+) -->"
    )
    now = int(time.time())
    for page in reversed(pages or []):
        for comment in reversed(page or []):
            match = marker_re.search(str(comment.get("body") or ""))
            if not match or match.group(1).lower() != pr.head_sha.lower():
                continue
            return now - int(match.group(2)) < retry_seconds
    return False


def dispatch_opencode_review(runner: Runner, repo: str, pr: PullRequest) -> None:
    runner.run(
        [
            "workflow",
            "run",
            "opencode-review.yml",
            "--repo",
            repo,
            "-f",
            f"pr_number={pr.number}",
            "-f",
            f"pr_base_ref={pr.base_ref}",
            "-f",
            f"pr_base_sha={pr.base_sha}",
            "-f",
            f"pr_head_sha={pr.head_sha}",
        ]
    )
    body = "\n".join(
        [
            f"{DISPATCH_MARKER} head_sha={pr.head_sha} epoch={int(time.time())} -->",
            "",
            "Scheduled OpenCode review dispatch for this PR head.",
            "",
            f"- Head SHA: `{pr.head_sha}`",
        ]
    )
    runner.run(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/issues/{pr.number}/comments",
            "-f",
            f"body={body}",
        ]
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
    trigger_reviews: bool = False,
    review_retry_seconds: int = 24 * 3600,
) -> int:
    numbers = list_open_pr_numbers(runner, repo)
    if not numbers:
        print("No open pull requests.")
        return 0

    approval_login = ""
    approval_available = True
    if merge and auto_approve and require_approval:
        approval_login = authenticated_login(runner)
        if approval_login == "github-actions[bot]":
            approval_available = False
            print(
                "Auto-approval disabled: github-actions[bot] cannot approve "
                "pull requests. Configure OPENCODE_APPROVE_TOKEN or use the "
                "OpenCode app token exchange."
            )

    merged = 0
    for number in numbers:
        pr = load_pr(runner, repo, number)

        if trigger_reviews and not pr.is_draft:
            if current_opencode_review_exists(runner, repo, pr):
                pass
            elif opencode_check_is_pending(pr.status_rollup):
                print(f"PR #{pr.number} waiting for OpenCode review.")
                continue
            elif recent_dispatch_marker_exists(
                runner,
                repo,
                pr,
                retry_seconds=review_retry_seconds,
            ):
                print(f"PR #{pr.number} OpenCode review recently dispatched.")
                continue
            else:
                dispatch_opencode_review(runner, repo, pr)
                print(f"PR #{pr.number} OpenCode review dispatched for {pr.head_sha}.")
                continue

        unresolved_threads = unresolved_review_thread_count(runner, repo, number)

        if merge and auto_approve and require_approval and pr.review_decision != "APPROVED":
            blockers = []
            if not approval_available:
                blockers.append(
                    f"approval actor {approval_login or 'unknown'} cannot approve PRs"
                )
            blockers.extend(auto_approval_blockers(pr, unresolved_threads))
            if blockers:
                print(f"PR #{pr.number} not auto-approved: {', '.join(blockers)}")
            else:
                try:
                    approve_pr(runner, repo, pr)
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or str(exc)).strip()
                    if "GitHub Actions is not permitted to approve pull requests" in detail:
                        detail = (
                            f"{detail} Configure OPENCODE_APPROVE_TOKEN or use the "
                            "OpenCode app token exchange."
                        )
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
    parser.add_argument(
        "--trigger-reviews",
        action="store_true",
        help="Dispatch OpenCode review for PR heads that lack one.",
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
            trigger_reviews=args.trigger_reviews,
        )
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
