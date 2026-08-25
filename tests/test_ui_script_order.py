"""Regression tests for client-side form initialization ordering."""

from pathlib import Path


def test_batch_controls_exist_before_inline_listener_registration() -> None:
    """Ensure batch controls are parsed before the inline script binds listeners."""
    source = Path("saas_web.py").read_text(encoding="utf-8")

    pairs = (
        (
            'id="batch_preset_buttons_container"',
            "document.getElementById('batch_preset_buttons_container').addEventListener",
        ),
        (
            'id="batch_target_bytes"',
            "document.getElementById('batch_target_bytes').addEventListener",
        ),
        (
            'id="shrink-batch-form"',
            "document.getElementById('shrink-batch-form').addEventListener",
        ),
    )

    for control_markup, listener_registration in pairs:
        assert source.index(control_markup) < source.index(listener_registration), (
            f"{control_markup} must be emitted before its listener is registered"
        )
