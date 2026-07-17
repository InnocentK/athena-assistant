"""
tests/test_ui_correctness.py — Web UI correctness guards (Milestone 26.10).

This repo has no JS runtime harness (existing UI tests are template/asset
presence checks, and a JS harness is on the project's "Later / unscheduled"
list). These are source-level structural assertions on the shipped frontend
assets — the same spirit as the existing presence tests — that lock the M26.10
fixes against regression. (Behavioural verification was done live with a
headless browser during implementation; see docs/TESTING.md.)
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CHAT_JS = (_ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
_CHAT_CSS = (_ROOT / "static" / "css" / "chat.css").read_text(encoding="utf-8")


# --- M1: failed answers are not recorded as assistant turns -----------------

def test_assistant_turn_recorded_only_on_success():
    # The assistant push must live inside the success branch, i.e. AFTER the
    # `data.success === false` check — never unconditionally before it.
    idx_check = _CHAT_JS.find("data.success === false")
    idx_push = _CHAT_JS.find('conversationHistory.push({ role: "assistant"')
    assert idx_check != -1 and idx_push != -1
    assert idx_push > idx_check, "assistant turn is pushed before the success check (M1 regressed)"


# --- M7: network catch is scoped; render errors don't become "Network error"-

def test_network_catch_is_scoped_to_fetch():
    # The fetch has its own try/catch that emits the network error, and the
    # outer block uses try/finally for state reset (not a broad catch that
    # would swallow render/TTS errors as "Network error").
    assert "} finally {" in _CHAT_JS
    # The "Network error" message is emitted only from the fetch failure path,
    # which sits just before a `return;` (so rendering is outside it).
    assert _CHAT_JS.count("Network error — could not reach the assistant.") == 1


# --- Voice global guard -----------------------------------------------------

def test_voice_access_is_guarded():
    assert 'typeof voice !== "undefined" && voice.isSupported' in _CHAT_JS
    assert 'typeof voice !== "undefined" && voice.isTTSSupported' in _CHAT_JS


# --- M3: canonical mode/provider always selectable --------------------------

def test_canonical_setting_values_are_injected_as_options():
    # Both mode and provider inject the canonical value as an option when it's
    # not already present, so a save can't silently clear/reset it.
    assert 'label: canonMode + " (current)"' in _CHAT_JS
    assert 'label: canonProv + " (current)"' in _CHAT_JS


# --- M6: panel loads are token-guarded --------------------------------------

def test_panel_load_token_guard_present():
    assert "_panelLoadToken" in _CHAT_JS
    # Each panel bumps its token and guards after awaits.
    assert "++_panelLoadToken.memory" in _CHAT_JS
    assert "++_panelLoadToken.settings" in _CHAT_JS
    assert "++_panelLoadToken.history" in _CHAT_JS
    assert "if (token !== _panelLoadToken.memory) return;" in _CHAT_JS
    assert "if (token !== _panelLoadToken.settings) return;" in _CHAT_JS
    assert "if (token !== _panelLoadToken.history) return;" in _CHAT_JS


def test_post_save_rerender_is_tab_guarded():
    assert 'if (_activeSettingsTab !== "profile") return;' in _CHAT_JS


# --- CSS: the previously-unstyled .history-count now has a rule --------------

def test_history_count_css_rule_present():
    assert ".history-count {" in _CHAT_CSS
    assert ".settings-note {" in _CHAT_CSS


# --- M30.4: attach input hidden; Files tab surfaces uploads ------------------

def test_attach_input_is_css_hidden():
    # There is deliberately NO bare `.hidden` rule in chat.css (scoped users
    # manage their own hiding), so the file input needs its own rule — without
    # it the native "Choose File" control renders in the footer.
    assert "#attach-input {" in _CHAT_CSS
    idx = _CHAT_CSS.find("#attach-input {")
    assert "display: none" in _CHAT_CSS[idx:idx + 80]


def test_files_panel_fetches_uploads_pattern():
    # M30.4: the Files tab merges the shallow "*" listing with `uploads/*` so
    # uploaded files are visible; the uploads fetch is best-effort.
    assert '"uploads/*"' in _CHAT_JS or "'uploads/*'" in _CHAT_JS


# --- M30.6: voice prefs are browser-local, opt-in, and complete ---------------

_VOICE_JS = (_ROOT / "static" / "js" / "voice.js").read_text(encoding="utf-8")


def test_voice_prefs_scaffolding_present():
    # localStorage-backed prefs with silent/off defaults (M30.6).
    assert '_VOICE_PREFS_KEY = "athena-voice-prefs"' in _CHAT_JS
    assert "speak: false" in _CHAT_JS       # read-aloud is opt-in
    assert "autoSend: false" in _CHAT_JS    # transcript review is the default
    # both TTS call sites are pref-gated (never unconditional again)
    assert _CHAT_JS.count(".speak &&") == 2


def test_voice_settings_section_rendered():
    assert '_settingsSectionTitle("Voice")' in _CHAT_JS
    assert '"Speak responses aloud"' in _CHAT_JS
    assert '"Auto-send voice transcript"' in _CHAT_JS
    assert '"Keep listening until stopped"' in _CHAT_JS


def test_voice_js_supports_continuous_and_voice_picker():
    assert "this.continuous" in _VOICE_JS
    assert "listVoices()" in _VOICE_JS
    assert "voiceschanged" in _CHAT_JS  # async voice loading handled
