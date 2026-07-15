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
     * Internal reference to the active SpeechRecognition instance.
     * @type {SpeechRecognition|null}
     * @private
     */
    this._recognition = null;
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
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    var self = this;

    recognition.onresult = function (event) {
      var transcript = event.results[0][0].transcript;
      self.onTranscript(transcript);
    };

    recognition.onerror = function (event) {
      self.onError("Speech recognition error: " + event.error);
    };

    recognition.onend = function () {
      self.isListening = false;
      self.onListeningStop();
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
   */
  speak(text) {
    if (!this.isTTSSupported) {
      return;
    }
    if (!text || text.trim().length === 0) {
      return;
    }

    window.speechSynthesis.cancel();

    var utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    window.speechSynthesis.speak(utterance);
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
