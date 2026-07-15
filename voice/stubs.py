"""
voice/stubs.py — Server-side voice processing stubs.

STATUS: Stubs only. The browser-based Web Speech API / SpeechSynthesis fallback
is active in Milestone 5. These stubs document the path to local STT/TTS.

LOCAL STT UPGRADE (faster-whisper):
  When ready to add local STT:
  1. pip install faster-whisper
  2. Implement transcribe_audio(audio_bytes: bytes, language: str = "en") -> str
     using faster-whisper's WhisperModel.
  3. Expose POST /voice/transcribe in main.py:
     - Accept multipart/form-data with an audio file (webm/wav/ogg)
     - Return {"transcript": "..."}
  4. In voice.js, POST the recorded Blob to /voice/transcribe instead of using
     the Web Speech API.
  5. Add WHISPER_MODEL_SIZE env var (default "base") to .env.example.
  Notes:
  - "base" model runs on CPU including Raspberry Pi (slow but functional).
  - "small" is a good balance for modern hardware.
  - Model files are downloaded on first use (~75–140 MB for base/small).
  - faster-whisper is significantly faster than openai-whisper on CPU.

LOCAL TTS UPGRADE (piper-tts):
  When ready to add local TTS:
  1. pip install piper-tts (or install the piper binary for your platform).
  2. Implement synthesize_speech(text: str, voice: str = "en_US-lessac-medium") -> bytes
     returning raw WAV bytes.
  3. Expose POST /voice/synthesize in main.py:
     - Accept JSON body {"text": "...", "voice": "..."}
     - Return audio/wav response
  4. In voice.js, fetch /voice/synthesize and play the returned audio bytes
     instead of using SpeechSynthesis.
  5. Add PIPER_VOICE env var to .env.example.
  Notes:
  - Piper voices are ~50–200 MB model files, downloaded separately.
  - Runs on CPU; real-time on modern hardware, slower on Pi.
  - See https://github.com/rhasspy/piper for voice model catalogue.

HARDWARE NOTES:
  - Raspberry Pi 4 (4 GB): faster-whisper "base" works, expect 5–15s transcription.
  - Older Mac/PC: whisper "small" is comfortable.
  - Raspberry Pi 3 / low-RAM: voice may be too slow; recommend browser fallback.
"""

from __future__ import annotations


def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    STUB — Local STT transcription using faster-whisper.

    Not implemented. See module docstring for upgrade instructions.
    """
    raise NotImplementedError(
        "Local STT is not yet implemented. "
        "See voice/stubs.py for the faster-whisper upgrade path."
    )


def synthesize_speech(text: str, voice: str = "en_US-lessac-medium") -> bytes:
    """
    STUB — Local TTS synthesis using piper-tts.

    Not implemented. See module docstring for upgrade instructions.
    """
    raise NotImplementedError(
        "Local TTS is not yet implemented. "
        "See voice/stubs.py for the piper-tts upgrade path."
    )
