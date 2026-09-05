"""Regression contracts for preset-button accessibility state."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from saas_web import app


def test_rendered_preset_state_uses_exact_valid_numeric_input() -> None:
    """Keep decimal and invalid numeric edits from selecting integer presets."""

    html = TestClient(app).get("/").text

    assert html.count('step="1"') >= 2
    assert html.count("const val = Number(this.value);") == 2
    assert html.count(
        "const hasValidPresetValue = "
        "this.value !== '' && Number.isFinite(val) && this.validity.valid;"
    ) == 2
    assert html.count("hasValidPresetValue && presetValue === val") == 2
    assert html.count("preview.innerText = 'Enter a whole number of bytes.';") == 2
    assert "const val = parseInt(this.value, 10);" not in html
