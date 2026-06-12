import subprocess
import unittest

from scripts import pr_review_merge


class FakeRunner:
    def __init__(self):
        self.json_outputs = []
        self.commands = []

    def run_json(self, args):
        self.commands.append(args)
        return self.json_outputs.pop(0)

    def run(self, args):
        self.commands.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="")


def pr_payload(**overrides):
    payload = {
        "number": 7,
        "title": "Test PR",
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
    def test_process_queue_merges_approved_clean_pr(self):
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
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
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

    def test_process_queue_does_not_auto_approve_failing_check(self):
        runner = FakeRunner()
        runner.json_outputs = [
            [{"number": 7}],
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

    def test_process_queue_does_not_auto_approve_dry_run(self):
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

    def test_process_queue_skips_unresolved_review_threads(self):
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
