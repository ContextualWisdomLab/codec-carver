"""Guard the inline upload-page script against pre-parsed batch controls."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _html_template() -> str:
    """Read ``HTML_TEMPLATE`` without importing optional web dependencies."""

    module = ast.parse((REPO_ROOT / "saas_web.py").read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "HTML_TEMPLATE"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError("HTML_TEMPLATE string assignment not found")


class WebScriptDomOrderTest(unittest.TestCase):
    """Keep batch-control initialization behind the batch-control markup."""

    def test_batch_controls_are_parsed_before_inline_script_executes(self) -> None:
        html = _html_template()
        script_start = html.index("<script>")
        script_end = html.index("</script>", script_start)
        batch_form = html.index('id="shrink-batch-form"')
        batch_preset_group = html.index('id="batch_preset_buttons_container"')
        batch_target = html.index('id="batch_target_bytes"')

        self.assertLess(batch_form, script_start)
        self.assertLess(batch_preset_group, script_start)
        self.assertLess(batch_target, script_start)
        self.assertLess(script_start, script_end)


if __name__ == "__main__":
    unittest.main()
