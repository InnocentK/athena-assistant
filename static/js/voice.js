/**
 * voice.js — Push-to-talk voice module for Athena Assistant
 *
 * Uses the Web Speech API for STT and the SpeechSynthesis API for TTS.
 * Both are browser-native — zero install required.
 *
 * Upgrade path:
 *   STT: Replace startListening() to POST audio to POST /voice/transcribe
 *        when a faster-whisper backend is available. See voice/stubs.py.
 *   TTS: Replace speak() to fetch POST /voice/synthesize and play returned
 *        audio bytes. See voice/stubs.py.
 *
 * Browser support:
 *   Web Speech API: Chrome, Edge (full). Firefox (limited — may need flag).
 *   SpeechSynthesis: All modern browsers.
 *
 * Milestone 5 — Athena Assistant
 */

"use strict";

class VoiceController {
  constructor() {
    /**
     * True if the browser supports the Web Speech API (STT).
     * @type {boolean}
     */
    this.isSupported = !!(
      window.SpeechRecognition || window.webkitSpeechRecognition
    );

    /**
     * True if the browser supports the SpeechSynthesis API (TTS).
     * @type {boolean}
     */
    this.isTTSSupported = !!window.speechSynthesis;

    /**
     * True while a speech recognition session is active.
     * @type {boolean}
     */
    this.isListening = false;

    /**
     * Called with the final transcript string when STT produces a result.
     * Set this callback before calling startListening().
     * @type {function(string): void}
     */
    this.onTranscript = function (_text) {};

    /**
     * Called with an error message string when STT encounters an error.
     * @type {function(string): void}
     */
    this.onError = function (_message) {};

    /**
     * Called when a listening session begins (microphone is active).
     * @type {function(): void}
     */
    this.onListeningStart = function () {};

    /**
     * Called when a listening session ends, whether from a result or timeout.
     * @type {function(): void}
     */
    this.onListeningStop = function () {};

    /**
     * M30.6: when true, recognition keeps listening across pauses until
     * stopListening() is called; final results accumulate and onTranscript
     * fires ONCE on end. When false (default), classic M5 single-utterance
     * behavior: stop at the first pause, deliver immediately.
     * @type {boolean}
     */
    this.continuous = false;

    /**
     * Internal reference to the active SpeechRecognition instance.
     * @type {SpeechRecognition|null}
     * @private
     */
    this._recognition = null;

    /**
     * Accumulated final transcripts for continuous mode (M30.6).
     * @type {string[]}
     * @private
     */
    this._buffer = [];
  }

  /**
   * Start a single-utterance speech recognition session.
   *
   * If the browser does not support the Web Speech API, onError is called
   * immediately. If a session is already active, this call is a no-op.
   *
   * To upgrade to server-side STT:
   *   1. Use MediaRecorder to capture audio as a Blob.
   *   2. POST the Blob to /voice/transcribe (multipart/form-data).
   *   3. Read {"transcript": "..."} from the response.
   *   4. Call this.onTranscript(transcript).
   *   See voice/stubs.py for full instructions.
   */
  startListening() {
    if (!this.isSupported) {
      this.onError(
        "Speech recognition is not supported in this browser. Try Chrome or Edge."
      );
      return;
    }

    if (this.isListening) {
      return;
    }

    var SpeechRecognitionImpl =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    var recognition = new SpeechRecognitionImpl();
    // M30.6: continuous mode keeps the mic open across pauses; the user ends
    // the session explicitly (click-to-stop). Default stays single-utterance.
    recognition.continuous = this.continuous;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    var self = this;
    this._buffer = [];

    recognition.onresult = function (event) {
      if (self.continuous) {
        // Accumulate every FINAL result; delivery happens once, on end.
        for (var i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            self._buffer.push(event.results[i][0].transcript);
          }
        }
        return;
      }
      var transcript = event.results[0][0].transcript;
      self.onTranscript(transcript);
    };

    recognition.onerror = function (event) {
      self.onError("Speech recognition error: " + event.error);
    };

    recognition.onend = function () {
      self.isListening = false;
      self.onListeningStop();
      if (self.continuous && self._buffer.length > 0) {
        var joined = self._buffer.join(" ").replace(/\s+/g, " ").trim();
        self._buffer = [];
        if (joined) {
          self.onTranscript(joined);
        }
      }
    };

    this._recognition = recognition;
    this.isListening = true;
    this.onListeningStart();
    recognition.start();
  }

  /**
   * Stop the active speech recognition session, if one is running.
   *
   * Calling this triggers the recognition's onend handler, which sets
   * isListening = false and calls onListeningStop().
   */
  stopListening() {
    if (this._recognition && this.isListening) {
      this._recognition.stop();
    }
  }

  /**
   * Speak the given text using the browser SpeechSynthesis API.
   *
   * Any speech currently in progress is cancelled before the new utterance
   * begins. Does nothing if TTS is not supported or the text is empty.
   *
   * To upgrade to server-side TTS:
   *   1. POST {"text": text, "voice": "en_US-lessac-medium"} to /voice/synthesize.
   *   2. Receive audio/wav bytes in the response.
   *   3. Create a Blob URL and play it with an Audio element.
   *   See voice/stubs.py for full instructions.
   *
   * @param {string} text - The text to synthesise and speak.
   * @param {string} [voiceName] - M30.6: a SpeechSynthesis voice name from
   *   listVoices(); unknown/empty falls back to the browser default.
   * @returns {SpeechSynthesisUtterance|null} M31.0: the utterance (so callers
   *   can watch `onend`), or null when TTS is unsupported or text is empty.
   */
  speak(text, voiceName) {
    var utterance = this._makeUtterance(text, voiceName);
    if (!utterance) {
      return null;
    }
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    return utterance;
  }

  /**
   * M31.0: like speak(), but WITHOUT the leading cancel() — the utterance
   * queues behind whatever is already speaking. This is the streaming-speech
   * primitive: conversation mode enqueues each completed sentence as chunks
   * arrive, and the synthesis engine plays them back-to-back (FIFO).
   *
   * @param {string} text
   * @param {string} [voiceName]
   * @returns {SpeechSynthesisUtterance|null} the queued utterance, or null.
   */
  enqueue(text, voiceName) {
    var utterance = this._makeUtterance(text, voiceName);
    if (!utterance) {
      return null;
    }
    window.speechSynthesis.speak(utterance);
    return utterance;
  }

  /**
   * Build a configured utterance for `text`, honoring the voice pick.
   * Returns null when TTS is unsupported or the text is empty (shared by
   * speak() and enqueue() — M31.0).
   * @private
   */
  _makeUtterance(text, voiceName) {
    if (!this.isTTSSupported) {
      return null;
    }
    if (!text || text.trim().length === 0) {
      return null;
    }

    var utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    if (voiceName) {
      var voices = this.listVoices();
      for (var i = 0; i < voices.length; i++) {
        if (voices[i].name === voiceName) {
          utterance.voice = voices[i];
          break;
        }
      }
      // No match → browser default (voices load async; never block speech).
    }
    return utterance;
  }

  /**
   * M30.6: the available SpeechSynthesis voices (may be empty until the
   * browser fires `voiceschanged`). Safe to call when TTS is unsupported.
   * @returns {SpeechSynthesisVoice[]}
   */
  listVoices() {
    if (!this.isTTSSupported || !window.speechSynthesis.getVoices) {
      return [];
    }
    try {
      return window.speechSynthesis.getVoices() || [];
    } catch (_) {
      return [];
    }
  }

  /**
   * Cancel any ongoing speech synthesis immediately.
   */
  cancelSpeech() {
    if (this.isTTSSupported) {
      window.speechSynthesis.cancel();
    }
  }
}

// Singleton — available globally as `voice` when this script is loaded before chat.js.
var voice = new VoiceController();
