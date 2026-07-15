"""
app/routers/voice.py — voice HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations


from fastapi import APIRouter, HTTPException




router = APIRouter()


@router.post(
    "/voice/transcribe",
    summary="Local STT stub — transcribe uploaded audio (not yet implemented)",
    include_in_schema=True,
)
async def voice_transcribe() -> dict[str, str]:
    """
    Stub endpoint for local server-side speech-to-text transcription.

    STATUS: Not implemented. The browser Web Speech API is active in Milestone 5.

    Expected interface when implemented:
      - Accept: multipart/form-data with an audio file field (webm / wav / ogg)
      - Return: {"transcript": "<transcribed text>"}

    Upgrade path:
      1. pip install faster-whisper
      2. Implement voice.stubs.transcribe_audio() using WhisperModel
      3. Replace this stub with a working handler that reads the uploaded audio,
         calls transcribe_audio(), and returns {"transcript": result}
      4. Update voice.js startListening() to POST recorded audio here
         instead of using the Web Speech API
      See voice/stubs.py for full step-by-step instructions.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Local STT not yet implemented. "
            "Browser Web Speech API is active. "
            "See voice/stubs.py for the faster-whisper upgrade path."
        ),
    )


@router.post(
    "/voice/synthesize",
    summary="Local TTS stub — synthesise speech from text (not yet implemented)",
    include_in_schema=True,
)
async def voice_synthesize() -> dict[str, str]:
    """
    Stub endpoint for local server-side text-to-speech synthesis.

    STATUS: Not implemented. The browser SpeechSynthesis API is active in Milestone 5.

    Expected interface when implemented:
      - Accept: JSON body {"text": "<text to speak>", "voice": "<piper voice name>"}
      - Return: audio/wav response (raw WAV bytes)

    Upgrade path:
      1. pip install piper-tts (or install the piper binary for your platform)
      2. Implement voice.stubs.synthesize_speech() using the piper library/binary
      3. Replace this stub with a working handler that calls synthesize_speech()
         and returns a Response with media_type="audio/wav"
      4. Update voice.js speak() to fetch this endpoint and play the audio bytes
         instead of using SpeechSynthesis
      See voice/stubs.py for full step-by-step instructions.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Local TTS not yet implemented. "
            "Browser SpeechSynthesis is active. "
            "See voice/stubs.py for the piper-tts upgrade path."
        ),
    )

