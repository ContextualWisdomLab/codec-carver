"""Executable contracts for the embedded SaaS browser UI."""

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

import saas_web


SOURCE_TEXT = (Path(__file__).resolve().parents[1] / "saas_web.py").read_text(
    encoding="utf-8"
)


class TestSaasUiContract(unittest.TestCase):
    """Keep DOM registration and nested-control handling safe."""

    def test_drop_zone_registration_waits_for_complete_dom(self):
        """Batch controls must exist before any listener looks them up."""
        self.assertIn("window.addEventListener('DOMContentLoaded'", SOURCE_TEXT)
        self.assertLess(
            SOURCE_TEXT.index("window.addEventListener('DOMContentLoaded'"),
            SOURCE_TEXT.index(
                "document.getElementById('batch_preset_buttons_container')"
            ),
        )
        self.assertIn("window.updateFileSizePreview = function(input)", SOURCE_TEXT)
        self.assertIn(
            'role="region" aria-label="File Upload Drop Zone"', SOURCE_TEXT
        )
        self.assertIn(
            'role="region" aria-label="Batch File Upload Drop Zone"', SOURCE_TEXT
        )

    def test_nested_interactive_elements_do_not_open_file_picker_twice(self):
        """A child span inside a label remains part of that interactive label."""
        self.assertEqual(
            SOURCE_TEXT.count("e.target.closest('input, button, label')"), 2
        )

    def test_drop_zone_click_behavior_executes_against_dom_harness(self):
        """Execute the generated script and prove both picker click boundaries."""
        node = shutil.which("node")
        self.assertIsNotNone(
            node,
            "Node.js is required for the embedded-browser UI contract test",
        )

        scripts = re.findall(
            r"<script>(.*?)</script>",
            saas_web.HTML_TEMPLATE,
            flags=re.DOTALL,
        )
        self.assertEqual(len(scripts), 1)
        script_literal = json.dumps(scripts[0])

        harness = textwrap.dedent(
            f"""
            const vm = require('node:vm');

            class FakeElement {{
              constructor(tagName = 'DIV', parentElement = null) {{
                this.tagName = tagName;
                this.parentElement = parentElement;
                this.listeners = new Map();
                this.clickCount = 0;
                this.dataset = {{}};
                this.style = {{}};
                this.files = [];
                this.value = '';
                this.classList = {{
                  contains: () => false,
                  add: () => {{}},
                  remove: () => {{}},
                }};
              }}

              addEventListener(type, callback) {{
                if (!this.listeners.has(type)) this.listeners.set(type, []);
                this.listeners.get(type).push(callback);
              }}

              dispatch(type, target = this) {{
                for (const callback of this.listeners.get(type) || []) {{
                  callback({{
                    target,
                    dataTransfer: {{ files: [] }},
                    preventDefault() {{}},
                    stopPropagation() {{}},
                    isTrusted: true,
                  }});
                }}
              }}

              closest(selector) {{
                const accepted = new Set(
                  selector.split(',').map((part) => part.trim().toUpperCase())
                );
                let current = this;
                while (current) {{
                  if (accepted.has(current.tagName)) return current;
                  current = current.parentElement;
                }}
                return null;
              }}

              click() {{
                this.clickCount += 1;
              }}

              setCustomValidity() {{}}
              removeAttribute() {{}}
              setAttribute() {{}}
            }}

            const ids = [
              'preset_buttons_container',
              'batch_preset_buttons_container',
              'target_bytes',
              'batch_target_bytes',
              'target_bytes_preview',
              'batch_target_bytes_preview',
              'shrink-form',
              'submit-btn',
              'batch_files_preview',
              'shrink-batch-form',
              'batch-submit-btn',
              'drop-zone',
              'batch-drop-zone',
              'file',
              'batch_files',
              'file_size_preview',
            ];

            const inputIds = new Set([
              'target_bytes',
              'batch_target_bytes',
              'file',
              'batch_files',
            ]);
            const buttonIds = new Set(['submit-btn', 'batch-submit-btn']);
            const elements = Object.fromEntries(
              ids.map((id) => [
                id,
                new FakeElement(
                  inputIds.has(id) ? 'INPUT' : buttonIds.has(id) ? 'BUTTON' : 'DIV'
                ),
              ])
            );

            const lateIds = new Set([
              'batch_preset_buttons_container',
              'batch_target_bytes',
              'batch_target_bytes_preview',
              'batch_files_preview',
              'shrink-batch-form',
              'batch-submit-btn',
              'batch-drop-zone',
              'batch_files',
            ]);
            let parserComplete = false;

            const document = {{
              body: new FakeElement('BODY'),
              getElementById(id) {{
                if (lateIds.has(id) && !parserComplete) return null;
                if (!(id in elements)) throw new Error(`missing fake element: ${{id}}`);
                return elements[id];
              }},
              querySelectorAll() {{
                return [];
              }},
            }};

            const windowListeners = new Map();
            const window = {{
              addEventListener(type, callback) {{
                windowListeners.set(type, callback);
              }},
            }};

            global.document = document;
            global.window = window;
            global.Event = class Event {{
              constructor(type, init = {{}}) {{
                this.type = type;
                Object.assign(this, init);
              }}
            }};

            vm.runInThisContext({script_literal});
            const ready = windowListeners.get('DOMContentLoaded');
            if (!ready) throw new Error('DOMContentLoaded registration missing');

            parserComplete = true;
            ready();

            const empty = new FakeElement('DIV');
            const input = new FakeElement('INPUT');
            const button = new FakeElement('BUTTON');
            const label = new FakeElement('LABEL');
            const nestedInLabel = new FakeElement('SPAN', label);

            const dropZone = elements['drop-zone'];
            const batchDropZone = elements['batch-drop-zone'];

            dropZone.dispatch('click', empty);
            batchDropZone.dispatch('click', empty);
            for (const target of [input, button, label, nestedInLabel]) {{
              dropZone.dispatch('click', target);
              batchDropZone.dispatch('click', target);
            }}

            process.stdout.write(JSON.stringify({{
              fileClicks: elements.file.clickCount,
              batchClicks: elements.batch_files.clickCount,
            }}));
            """
        )

        completed = subprocess.run(
            [node, "-e", harness],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"fileClicks": 1, "batchClicks": 1},
        )


if __name__ == "__main__":
    unittest.main()
