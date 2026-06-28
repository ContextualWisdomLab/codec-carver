"""Module docstring."""
import subprocess
import unittest

from scripts import pr_review_merge


class FakeRunner:
    """Class docstring."""
    def __init__(self):
        """Docstring."""
        self.json_outputs = []
        self.run_outputs = []
        self.commands = []

    def run_json(self, args):
        """Docstring."""
        self.commands.append(args)
        return self.json_outputs.pop(0)

    def run(self, args):
        """Docstring."""
        self.commands.append(args)
        if self.run_outputs:
            output = self.run_outputs.pop(0)
            if isinstance(output, BaseException):
                raise output
            return output
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="")


def pr_payload(**overrides):
    """Docstring."""
    payload = {
        "number": 7,
        "title": "Test PR",
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefOid": "abc123",
        "isDraft": False,
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "APPROVED",
        "statusCheckRollup": [
            {"__typename": "StatusContext", "context": "CodeRabbit", "state": "SUCCESS"}
        ],
    }
    payload.update(overrides)
    return payload


def threads_payload(*nodes):
    """Docstring."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": list(nodes),
                    }
                }
            }
        }
    }


class ReviewMergeTests(unittest.TestCase):
    """Test class docstring."""
    def test_process_queue_merges_approved_clean_pr(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
        )

        self.assertEqual(merged, 1)
        self.assertIn(
            [
                "pr",
                "merge",
                "7",
                "--repo",
                "owner/repo",
                "--merge",
                "--match-head-commit",
                "abc123",
            ],
            runner.commands,
        )

    def test_process_queue_skips_without_required_approval(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(reviewDecision="REVIEW_REQUIRED"),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))

    def test_process_queue_auto_approves_then_merges(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            {"login": "opencode-agent[bot]"},
            pr_payload(reviewDecision="REVIEW_REQUIRED", mergeStateStatus="BLOCKED"),
            threads_payload(),
            pr_payload(reviewDecision="APPROVED", mergeStateStatus="CLEAN"),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
            auto_approve=True,
        )

        self.assertEqual(merged, 1)
        self.assertIn(
            ["pr", "review", "7", "--repo", "owner/repo", "--approve", "--body"],
            [command[:7] for command in runner.commands],
        )
        self.assertIn(
            [
                "pr",
                "merge",
                "7",
                "--repo",
                "owner/repo",
                "--merge",
                "--match-head-commit",
                "abc123",
            ],
            runner.commands,
        )

    def test_process_queue_treats_already_merged_race_as_success(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(),
            threads_payload(),
            {
                "state": "MERGED",
                "mergedAt": "2026-06-12T07:02:31Z",
                "mergeCommit": {"oid": "merge123"},
            },
        ]
        runner.run_outputs = [
            subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", "pr", "merge", "7"],
                stderr="Pull request already merged",
            )
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
        )

        self.assertEqual(merged, 1)
        self.assertIn(
            [
                "pr",
                "view",
                "7",
                "--repo",
                "owner/repo",
                "--json",
                "state,mergedAt,mergeCommit",
            ],
            runner.commands,
        )

    def test_process_queue_does_not_auto_approve_failing_check(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            {"login": "opencode-agent[bot]"},
            pr_payload(
                mergeStateStatus="BLOCKED",
                reviewDecision="REVIEW_REQUIRED",
                statusCheckRollup=[
                    {
                        "__typename": "StatusContext",
                        "context": "CodeRabbit",
                        "state": "FAILURE",
                    }
                ],
            ),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
            auto_approve=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["pr", "review", "7"] for command in runner.commands))
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))

    def test_process_queue_skips_auto_approval_with_github_actions_token(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            {"login": "github-actions[bot]"},
            pr_payload(reviewDecision="REVIEW_REQUIRED", mergeStateStatus="BLOCKED"),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
            auto_approve=True,
        )

        self.assertEqual(merged, 0)
        self.assertIn(["api", "user"], runner.commands)
        self.assertFalse(any(command[:3] == ["pr", "review", "7"] for command in runner.commands))
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))

    def test_process_queue_does_not_auto_approve_dry_run(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(reviewDecision="REVIEW_REQUIRED", mergeStateStatus="BLOCKED"),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=False,
            require_approval=True,
            auto_approve=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["pr", "review", "7"] for command in runner.commands))
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))

    def test_process_queue_dispatches_missing_opencode_review(self):
        """Test docstring."""
        head = "a" * 40
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(headRefOid=head, reviewDecision="REVIEW_REQUIRED"),
            [[]],
            [[]],
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
            trigger_reviews=True,
        )

        self.assertEqual(merged, 0)
        self.assertIn(
            [
                "workflow",
                "run",
                "opencode-review.yml",
                "--repo",
                "owner/repo",
                "-f",
                "pr_number=7",
                "-f",
                "pr_base_ref=main",
                "-f",
                f"pr_base_sha={'b' * 40}",
                "-f",
                f"pr_head_sha={head}",
            ],
            runner.commands,
        )
        self.assertTrue(
            any(command[:4] == ["api", "-X", "POST", "repos/owner/repo/issues/7/comments"] for command in runner.commands)
        )

    def test_process_queue_does_not_repeat_recent_opencode_dispatch(self):
        """Test docstring."""
        head = "a" * 40
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(headRefOid=head, reviewDecision="REVIEW_REQUIRED"),
            [[]],
            [
                [
                    {
                        "body": (
                            "<!-- scheduled-pr-review-merge opencode-dispatch "
                            f"head_sha={head} epoch={int(pr_review_merge.time.time())} -->"
                        )
                    }
                ]
            ],
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
            trigger_reviews=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["workflow", "run", "opencode-review.yml"] for command in runner.commands))

    def test_process_queue_skips_unresolved_review_threads(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(),
            threads_payload({"isResolved": False, "isOutdated": False}),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))

    def test_process_queue_skips_failing_check(self):
        """Test docstring."""
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
            pr_payload(
                statusCheckRollup=[
                    {
                        "__typename": "StatusContext",
                        "context": "CodeRabbit",
                        "state": "FAILURE",
                    }
                ]
            ),
            threads_payload(),
        ]

        merged = pr_review_merge.process_queue(
            runner,
            "owner/repo",
            merge=True,
            require_approval=True,
        )

        self.assertEqual(merged, 0)
        self.assertFalse(any(command[:3] == ["pr", "merge", "7"] for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
