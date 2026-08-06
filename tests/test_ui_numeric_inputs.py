
import time
import subprocess
import unittest

try:
    import pytest
    from playwright.sync_api import Page, expect
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

if _HAS_PLAYWRIGHT:
    @pytest.fixture(scope="module")
    def live_server():
        process = subprocess.Popen(["python3", "saas_web.py"])
        time.sleep(2)
        yield "http://localhost:8000"
        process.terminate()
        process.wait()

    def test_ui_numeric_inputs_empty_state_transitions(page: Page, live_server):
        page.goto(live_server)

        for input_id in ['target_bytes', 'batch_target_bytes']:
            input_locator = page.locator(f'#{input_id}')
            preview_locator = page.locator(f'#{input_id}_preview')

            container_id = 'preset_buttons_container' if input_id == 'target_bytes' else 'batch_preset_buttons_container'
            btn_locator = page.locator(f'#{container_id} .preset-btn').first

            # Error state (negative number)
            input_locator.evaluate("e => e.value = '-100'")
            input_locator.evaluate("e => e.dispatchEvent(new Event('input', { bubbles: true }))")
            expect(input_locator).to_have_attribute('aria-invalid', 'true')
            expect(preview_locator).to_have_text('Must be greater than 0.')

            # Error -> Empty
            input_locator.evaluate("e => e.value = ''")
            input_locator.evaluate("e => e.dispatchEvent(new Event('input', { bubbles: true }))")
            expect(input_locator).not_to_have_attribute('aria-invalid', 'true')
            expect(preview_locator).to_have_text('')

            # Empty -> Valid
            input_locator.evaluate("e => e.value = '1024'")
            input_locator.evaluate("e => e.dispatchEvent(new Event('input', { bubbles: true }))")
            expect(input_locator).not_to_have_attribute('aria-invalid', 'true')
            expect(preview_locator).to_have_text('1.00 KiB')

            # Preset valid -> Empty
            btn_locator.click()
            expect(btn_locator).to_have_attribute('aria-pressed', 'true')

            input_locator.evaluate("e => e.value = ''")
            input_locator.evaluate("e => e.dispatchEvent(new Event('input', { bubbles: true }))")
            expect(input_locator).not_to_have_attribute('aria-invalid', 'true')
            expect(preview_locator).to_have_text('')
            expect(btn_locator).to_have_attribute('aria-pressed', 'false')
else:
    class DummyTest(unittest.TestCase):
        def test_dummy(self):
            pass
