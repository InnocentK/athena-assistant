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
    # M31.0 (A2) evolved the M30.6 `.speak &&` count pin, per REVIEW-3.0.z B5
    # ("extend the pin consciously, never delete it"): both whole-reply TTS
    # call sites now gate through the ONE shared helper — definition + the
    # streaming done-path + the buffered path. A fourth `_shouldSpeak(` means
    # a new speech site was added without thinking about conversation mode.
    assert _CHAT_JS.count("_shouldSpeak(") == 3
    assert ".speak &&" not in _CHAT_JS      # no stray direct gates remain


def test_voice_settings_section_rendered():
    assert '_settingsSectionTitle("Voice")' in _CHAT_JS
    assert '"Conversation mode"' in _CHAT_JS       # M31.0
    assert '"Speak responses aloud"' in _CHAT_JS
    assert '"Auto-send voice transcript"' in _CHAT_JS
    assert '"Keep listening until stopped"' in _CHAT_JS


def test_voice_js_supports_continuous_and_voice_picker():
    assert "this.continuous" in _VOICE_JS
    assert "listVoices()" in _VOICE_JS
    assert "voiceschanged" in _CHAT_JS  # async voice loading handled


# --- M31.0: conversation mode — structure pins --------------------------------

def test_conversation_mode_default_off_and_gated():
    # The pref exists, defaults OFF, and the streaming sentence path is gated
    # on `conversation` (not on `speak`) — A2's second assertion.
    assert "conversation: false" in _CHAT_JS
    assert "if (!vp.conversation) return null" in _CHAT_JS  # _beginConvoTurn gate


def test_enqueue_never_cancels():
    # voice.js: enqueue() (and the shared _makeUtterance below it) must never
    # cancel — cancelling would clip the sentence currently being spoken.
    # speak() keeps its cancel-then-say contract for Test-voice / whole-reply.
    # Anchors are the two DEFINITION lines (`… {`), which are unique — doc
    # comments mention these names earlier and would corrupt looser slices.
    start = _VOICE_JS.index("enqueue(text, voiceName) {")
    end = _VOICE_JS.index("_makeUtterance(text, voiceName) {")
    segment = _VOICE_JS[start:end]
    assert "_makeUtterance" in segment  # enqueue delegates to the shared builder
    assert "cancel" not in segment
    # A4: speak() hands back its utterance so callers can watch `onend`.
    assert "return utterance" in _VOICE_JS


def test_done_path_tail_is_streamed_text_not_reconciled():
    # The done-event's authoritative-text reconcile stays visual-only: the
    # spoken tail always derives from the ASSEMBLED streamed text.
    assert "assembled.slice(convo.spokenUpTo)" in _CHAT_JS


def test_mobile_layout_keeps_mic_button():
    # M31.1: conversation mode arms ONLY from the mic button, so phones must
    # have it. M28.4's space-saving `display: none` (from before the Voice
    # epic) must never return: the narrow-screen media block may RESTYLE
    # #ptt-btn (it slims it), but never hide it.
    mq = _CHAT_CSS[_CHAT_CSS.index("@media (max-width: 600px)"):]
    assert "#ptt-btn" in mq  # the compensating size rule exists
    idx = mq.find("#ptt-btn")
    while idx != -1:
        block = mq[idx:mq.index("}", idx)]
        assert "display: none" not in block
        idx = mq.find("#ptt-btn", idx + 1)


def test_hands_free_loop_requires_gesture_and_stops_everywhere():
    # The loop arms ONLY inside the mic-click handler (browser gesture
    # policies): definition + exactly one call site. A second arm site means
    # auto-listen could start without a user gesture — rethink before bumping.
    assert _CHAT_JS.count("_convoArm()") == 2
    # Every stop condition is wired (definition + five disarm sites: mic-off
    # click, STT error, hidden tab, typed send, settings toggle-off).
    assert _CHAT_JS.count("_convoDisarm()") == 6
    assert "visibilitychange" in _CHAT_JS
    # M31.2: the turn earcon blips ONLY from the auto-reopen path (definition
    # + the one _convoResume call site), and its AudioContext unlock rides
    # the same arming mic-click gesture (definition + the one arm-branch
    # call site) — a second call site of either means the gesture/auto-only
    # contract changed; rethink before bumping.
    assert _CHAT_JS.count("_playTurnEarcon(") == 2
    assert _CHAT_JS.count("_earconUnlock(") == 2


# --- M31.3/M31.4: save reply as file — structure pins --------------------------

def test_save_reply_reuses_upload_envelope():
    # The per-reply Save button is USER-initiated (the pure-LLM provider
    # policy is untouched) and its server copy posts through the EXISTING
    # /files/upload envelope with the FIXED dest enum — definition + exactly
    # two render call sites (appendMessage assistant meta +
    # _finishStreamingBubble). A new write endpoint here would be a second
    # filesystem write path — do not.
    assert _CHAT_JS.count("_replySaveButton(") == 3
    seg = _CHAT_JS[_CHAT_JS.index("function _replySaveButton"):]
    seg = seg[:seg.index("\nfunction appendMessage")]
    assert '"/files/upload"' in seg           # the one write path
    assert '("dest", "saved")' in seg         # the fixed enum value, literal
    assert ".reply-save-btn" in _CHAT_CSS


def test_save_reply_filenames_and_prefs():
    # M31.4: derived filenames (heading/first-words; timestamp fallback
    # keeps the reply- prefix) — definition + the ONE call inside the save
    # button; destinations are browser-local prefs with server ON / device
    # OFF defaults (shipping M31.3 behavior preserved).
    assert _CHAT_JS.count("_replyFilename(") == 2
    fn_seg = _CHAT_JS[_CHAT_JS.index("function _replyFilename"):]
    fn_seg = fn_seg[:fn_seg.index("\nfunction ")]
    assert '"reply-"' in fn_seg or "'reply-'" in fn_seg
    assert '_SAVE_PREFS_KEY = "athena-save-prefs"' in _CHAT_JS
    assert "server: true" in _CHAT_JS
    assert "device: false" in _CHAT_JS
    assert '"Saving replies"' in _CHAT_JS     # the settings section exists
