# Product technical gap baseline

Status: Proposed
Predecessor pull request: #655
Predecessor exact head reviewed: `87010ebfc4d887f25935e43d93e91810002576e2`
Successor branch: `codex/design-assurance-codec-carver-655-20260930`

## Goal and ownership

This successor preserves the valid UI delta from #655 after a concurrent commit restored listener registration before the batch controls and deleted its regression test and evidence baseline. Codec Carver remains the canonical writer for this SaaS UI.

The shared dependency repair is owned separately by Draft PR #558. PR #662 must consume that fix through ordinary integration/restack; it must not copy the dependency delta.

## Root cause and acceptance matrix

The inline script dereferenced `batch_preset_buttons_container` and `batch_target_bytes` before the browser parsed their markup. The resulting null dereference stopped the script and prevented subsequent UI listeners from registering.

Exact-head Security evidence for `1603af38c1f9e74ca1134fbf191804eaf41cece3` also failed in run `36685207628`, job `109843446703`: Trivy reported CVE-2026-84382 (HIGH), CVE-2026-84378, CVE-2026-84379, and CVE-2026-84380 against unused `httpx2==2.5.0`. Canonical owner PR #558 at `21824f77e9ee4c26c42bb1f21f00eaa3ae21fb6d` removes `httpx2` and `httpcore2` from `pyproject.toml`, `requirements.txt`, and `requirements-lock.txt`; its Security check is GREEN, while its CodeQL PR check still requires resolution.

| Capability | Current evidence | Status | Required action |
| --- | --- | --- | --- |
| Deterministic listener registration | Script is after all page markup; focused source-order test restored | GREEN (source contract) | Keep exact-head unit suite green |
| Dependency security | PR #662 Security failed on four `httpx2==2.5.0` CVEs; canonical removal is in #558 | FAIL — OWNER ROUTED | Integrate #558 normally, non-force restack #662, then rerun exact-head Security |
| Pointer, touch, keyboard | Listener path repaired | NOT REVALIDATED | Exercise preset buttons, inputs, drop zones, and submit flows in a real browser |
| Lifecycle and race cleanup | Existing delta does not prove abort/retry/stale-response cleanup | FAIL | Add browser scenarios and cleanup assertions |
| Loading/empty/error/offline/permission/read-only/stale/conflict/retry/busy | Current-head evidence incomplete | FAIL | Cover every applicable state |
| Responsive layouts | No current-head desktop/mobile/intermediate screenshots | FAIL | Capture three viewport classes |
| WCAG 2.2 AA and reduced motion | Source semantics remain; automated/browser evidence incomplete | FAIL | Run axe, keyboard, touch-target, and reduced-motion checks |
| Locales | ko/en/ja/zh/vi/es/de/fr evidence absent | FAIL | Add versioned translations and locale E2E |
| Large data, import/export, persistence, recovery | Batch flow affected; recovery evidence absent | FAIL | Run realistic batch-size and reload/retry recovery tests |

## Merge gate

Keep this PR Draft until #558 is integrated and #662 is restacked without force, exact-head Checks are green, and real-browser interaction, responsive evidence, accessibility and locale coverage, large-data behavior, recovery, and required review are green. The predecessor remains open; no valid delta is discarded.
