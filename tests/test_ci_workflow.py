"""Regression tests for the repository CI workflow contract."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FUZZ_WORKFLOW = ROOT / ".github" / "workflows" / "fuzz.yml"


class CiWorkflowTests(unittest.TestCase):
    """Keep Rust CI reproducible on runners without a suitable default toolchain."""

    def test_rust_job_installs_and_uses_rust_1_88_with_rustfmt(self) -> None:
        """Require edition-2024 Rust and rustfmt before formatting or tests run."""

        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        toolchain = "1.88.0"
        install = f"rustup toolchain install {toolchain} --profile minimal --component rustfmt"
        formatting = (
            f"rustup run {toolchain} cargo fmt --manifest-path "
            "rust-core/Cargo.toml -- --check"
        )
        tests = (
            f"rustup run {toolchain} cargo test --locked --all-targets "
            "--manifest-path rust-core/Cargo.toml"
        )

        self.assertIn(install, workflow)
        self.assertIn(formatting, workflow)
        self.assertIn(tests, workflow)
        self.assertLess(workflow.index(install), workflow.index(formatting))
        self.assertLess(workflow.index(install), workflow.index(tests))

    def test_rust_job_compiles_linux_and_macos_backends(self) -> None:
        """Compile platform-specific Rust paths on Linux and macOS runners."""

        workflow = CI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertIn("os: [ubuntu-latest, macos-latest]", workflow)

    def test_checkout_does_not_persist_credentials(self) -> None:
        """Keep the read-only workflow token out of later build steps."""

        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        lines = workflow.splitlines()
        checkout_steps = []
        for index, line in enumerate(lines):
            if not line.strip().startswith("- uses: actions/checkout@"):
                continue
            indentation = len(line) - len(line.lstrip())
            step = [line]
            for candidate in lines[index + 1 :]:
                candidate_indentation = len(candidate) - len(candidate.lstrip())
                if (
                    candidate.strip().startswith("- ")
                    and candidate_indentation <= indentation
                ):
                    break
                step.append(candidate)
            checkout_steps.append("\n".join(step))

        self.assertEqual(len(checkout_steps), 2)
        for step in checkout_steps:
            with self.subTest(step=step.splitlines()[0].strip()):
                self.assertIn("persist-credentials: false", step)

    def test_workflows_only_cancel_superseded_pull_request_heads(self) -> None:
        """Keep non-PR runs isolated while grouping each workflow by PR."""

        for workflow_path in (CI_WORKFLOW, FUZZ_WORKFLOW):
            with self.subTest(workflow=workflow_path.name):
                workflow = workflow_path.read_text(encoding="utf-8")
                self.assertIn("${{ github.workflow }}-${{ github.repository }}", workflow)
                self.assertIn("format('pr-{0}', github.event.pull_request.number)", workflow)
                self.assertIn("format('run-{0}', github.run_id)", workflow)
                self.assertIn(
                    "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
                    workflow,
                )
                self.assertIn("max-parallel: 1", workflow)

    def test_fuzz_does_not_repeat_the_ci_test_suite(self) -> None:
        """Run the full unittest suite only in CI, not again in fuzz."""

        workflow = FUZZ_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("python -m unittest discover", workflow)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
