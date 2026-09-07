"""
Voice input handler for JARVIS desktop assistant.
Provides optional speech-to-text recognition with graceful fallback.
Wraps VoiceManager for backwards compatibility.
"""

from typing import Optional
from voice.voice_manager import VoiceManager, voice_manager


class VoiceInputHandler:
    """Manages audio capture and transcription, delegating to VoiceManager."""

    def __init__(self, manager: Optional[VoiceManager] = None):
        self.manager = manager or voice_manager

    @property
    def is_available(self) -> bool:
        """Check whether voice recognition hardware and libraries are available."""
        return self.manager.is_stt_available

    def listen_and_transcribe(self, timeout: int = 5, phrase_time_limit: int = 10) -> Optional[str]:
        """
        Listen to microphone and transcribe speech to text.
        :return: Transcribed string or None if failed/unavailable
        """
        return self.manager.listen_once(timeout=timeout, phrase_time_limit=phrase_time_limit)
