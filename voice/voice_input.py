"""
Voice input handler for JARVIS desktop assistant.
Provides optional speech-to-text recognition with graceful fallback.
"""

from typing import Optional


class VoiceInputHandler:
    """Manages audio capture and transcription via speech_recognition if available."""

    def __init__(self):
        self._sr = None
        self._recognizer = None
        self._microphone = None
        self._available = False

        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._microphone = sr.Microphone()
            self._available = True
        except (ImportError, OSError, Exception):
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check whether voice recognition hardware and libraries are available."""
        return self._available

    def listen_and_transcribe(self, timeout: int = 5, phrase_time_limit: int = 10) -> Optional[str]:
        """
        Listen to microphone and transcribe speech to text.
        :return: Transcribed string or None if failed/unavailable
        """
        if not self._available or not self._recognizer or not self._microphone:
            print("[Voice] Speech recognition hardware or 'speech_recognition' package is not installed/configured.")
            print("[Voice] Please type your query in text.")
            return None

        try:
            print("\n[Voice] Listening... Speak now.")
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            print("[Voice] Processing audio...")
            text = self._recognizer.recognize_google(audio)
            print(f"[Voice] Transcribed: \"{text}\"")
            return text
        except Exception as e:
            print(f"[Voice] Recognition error: {e}")
            return None
