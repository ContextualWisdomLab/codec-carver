"""Regression tests for the repository CI workflow contract."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class CiWorkflowTests(unittest.TestCase):
    """Keep Rust CI reproducible on runners without a suitable default toolchain."""

    def test_rust_job_installs_and_uses_rust_1_88_with_rustfmt(self) -> None:
        """Require edition-2024 Rust and rustfmt before formatting or tests run."""

        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        install = (
            "rustup toolchain install 1.88.0 --profile minimal --component rustfmt"
        )
        formatting = "rustup run 1.88.0 cargo fmt --manifest-path rust-core/Cargo.toml -- --check"
        tests = (
            "rustup run 1.88.0 cargo test --locked --all-targets "
            "--manifest-path rust-core/Cargo.toml"
        )

        self.assertIn(install, workflow)
        self.assertIn(formatting, workflow)
        self.assertIn(tests, workflow)
        self.assertLess(workflow.index(install), workflow.index(formatting))
        self.assertLess(workflow.index(install), workflow.index(tests))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
