"""
Ambient Voice Loop and Speech Engine for JARVIS desktop assistant.
Provides Azure neural text-to-speech (edge-tts) with smooth pygame streaming,
offline pyttsx3 fallback, and ambient speech-to-text recognition.
"""

import asyncio
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from colorama import Fore, Style

from config import config

# Optional imports handled defensively
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False


class VoiceManager:
    """
    Unified voice and speech manager for JARVIS.
    Handles neural TTS with offline fallback, audio playback,
    and ambient STT with wake-word detection.
    """

    def __init__(
        self,
        tts_voice: Optional[str] = None,
        wake_word: Optional[str] = None,
        listen_timeout: Optional[int] = None,
        phrase_time_limit: Optional[int] = None,
    ):
        self.tts_voice = tts_voice or config.tts_voice
        self.wake_word = (wake_word or config.wake_word).strip().lower()
        self.listen_timeout = listen_timeout or config.listen_timeout
        self.phrase_time_limit = phrase_time_limit or config.phrase_time_limit

        self._speech_lock = threading.Lock()
        self._stop_requested = False
        self._is_continuous_listening = False

        # STT Initialization
        self._recognizer: Optional[sr.Recognizer] = None
        self._microphone: Optional[sr.Microphone] = None
        self._stt_available = False

        if HAS_SR:
            try:
                self._recognizer = sr.Recognizer()
                self._microphone = sr.Microphone()
                self._stt_available = True
            except Exception:
                self._stt_available = False

        # Cache directory for synthesized audio
        self.cache_dir = Path(tempfile.gettempdir()) / "jarvis_tts"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @property
    def is_tts_available(self) -> bool:
        """Return True if at least one TTS engine (edge-tts or pyttsx3) is available."""
        return HAS_EDGE_TTS or HAS_PYTTSX3

    @property
    def is_stt_available(self) -> bool:
        """Return True if microphone capture and speech recognition are available."""
        return self._stt_available and self._recognizer is not None and self._microphone is not None

    @staticmethod
    def clean_text_for_speech(text: str) -> str:
        """
        Sanitize text before speech synthesis by removing Markdown,
        fenced code blocks, URLs, system delimiters, and ReAct headers.
        """
        if not text:
            return ""

        cleaned = text

        # Strip markdown fenced code blocks: ```lang ... ```
        cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)

        # Strip inline code formatting: `code` -> code
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

        # Strip markdown links: [text](url) -> text
        cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

        # Strip raw URLs
        cleaned = re.sub(r"https?://\S+", "", cleaned)

        # Strip special model/system delimiter tokens
        tokens_to_strip = [
            r"<channel\|>",
            r"<end_of_turn>",
            r"<start_of_turn>",
            r"<\|im_end\|>",
            r"<\|im_start\|>",
            r"<\|eot_id\|>",
            r"\[truncated.*?\]",
        ]
        for token in tokens_to_strip:
            cleaned = re.sub(token, "", cleaned, flags=re.IGNORECASE)

        # Strip ReAct step headers at line starts
        cleaned = re.sub(
            r"^(Thought|Plan|Critique|Action|Action Input|Observation|Final Answer)\s*:\s*",
            "",
            cleaned,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # Strip markdown headers (#, ##, etc.)
        cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)

        # Strip markdown styling characters (*, **, _, __, ~~)
        cleaned = re.sub(r"[*_~]{1,3}", "", cleaned)

        # Strip blockquotes (>) and bullet points at line starts
        cleaned = re.sub(r"^[\s*>#-]+\s*", "", cleaned, flags=re.MULTILINE)

        # Normalize multiple spaces and line breaks
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    def speak(self, text: str, non_blocking: bool = True) -> None:
        """
        Synthesize speech and play audio asynchronously or synchronously.
        Attempts edge-tts (Azure neural voice) streaming via pygame.
        Gracefully falls back to offline pyttsx3 on error or disconnection.
        """
        clean_text = self.clean_text_for_speech(text)
        if not clean_text:
            return

        if non_blocking:
            thread = threading.Thread(
                target=self._speak_sync,
                args=(clean_text,),
                daemon=True,
                name="JARVIS-TTS-Thread",
            )
            thread.start()
        else:
            self._speak_sync(clean_text)

    def _speak_sync(self, clean_text: str) -> None:
        """Internal synchronous speech execution protected by speech lock."""
        with self._speech_lock:
            self._stop_requested = False

            # Primary attempt: edge-tts + pygame
            if HAS_EDGE_TTS and HAS_PYGAME:
                success = self._speak_edge_tts(clean_text)
                if success:
                    return

            # Offline fallback: pyttsx3
            if HAS_PYTTSX3:
                self._speak_pyttsx3(clean_text)

    def _speak_edge_tts(self, text: str) -> bool:
        """Synthesize via edge-tts and stream through pygame.mixer."""
        temp_audio: Optional[Path] = None
        try:
            # Ensure pygame mixer is initialized
            if not pygame.mixer.get_init():
                pygame.mixer.init()

            temp_audio = self.cache_dir / f"tts_{uuid.uuid4().hex[:8]}.mp3"

            async def _synthesize():
                communicate = edge_tts.Communicate(text, voice=self.tts_voice)
                await communicate.save(str(temp_audio))

            # Run asynchronous edge-tts synthesis
            asyncio.run(_synthesize())

            if not temp_audio.exists() or temp_audio.stat().st_size == 0:
                return False

            # Stop any currently playing audio
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()

            pygame.mixer.music.load(str(temp_audio))
            pygame.mixer.music.play()

            # Wait for playback completion while monitoring stop request
            while pygame.mixer.music.get_busy() and not self._stop_requested:
                time.sleep(0.05)

            if self._stop_requested:
                pygame.mixer.music.stop()

            pygame.mixer.music.unload()
            return True

        except Exception:
            return False
        finally:
            if temp_audio and temp_audio.exists():
                try:
                    temp_audio.unlink(missing_ok=True)
                except Exception:
                    pass

    def _speak_pyttsx3(self, text: str) -> bool:
        """Offline fallback speech using pyttsx3 SAPI5/local TTS engine."""
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception:
            return False

    def stop_speech(self) -> None:
        """Immediately interrupt any ongoing audio playback."""
        self._stop_requested = True
        try:
            if HAS_PYGAME and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def listen_once(
        self,
        timeout: Optional[int] = None,
        phrase_time_limit: Optional[int] = None,
    ) -> Optional[str]:
        """
        Listen to microphone input once and transcribe speech to text.
        :param timeout: Silence duration limit before giving up (seconds)
        :param phrase_time_limit: Max continuous duration for a single phrase
        :return: Transcribed string or None if unrecognized/timed out/unavailable
        """
        timeout = timeout or self.listen_timeout
        phrase_time_limit = phrase_time_limit or self.phrase_time_limit

        if not self.is_stt_available:
            print(
                f"{Fore.YELLOW}[Voice] Speech recognition hardware or PyAudio is unavailable on this system.\n"
                f"        Please enter commands directly via keyboard.{Style.RESET_ALL}"
            )
            return None

        try:
            print(f"\n{Fore.CYAN}[Listening...] Speak now.{Style.RESET_ALL}")
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )

            print(f"{Fore.CYAN}[Processing voice...]{Style.RESET_ALL}")
            transcription = self._recognizer.recognize_google(audio)
            cleaned = transcription.strip() if transcription else None
            if cleaned:
                print(f"{Fore.GREEN}[Voice Transcribed]: \"{cleaned}\"{Style.RESET_ALL}")
            return cleaned

        except sr.WaitTimeoutError:
            print(f"{Fore.LIGHTBLACK_EX}[Voice: Listening timed out (no speech detected)]{Style.RESET_ALL}")
            return None
        except sr.UnknownValueError:
            print(f"{Fore.LIGHTBLACK_EX}[Voice: Speech could not be understood]{Style.RESET_ALL}")
            return None
        except Exception as e:
            print(f"{Fore.RED}[Voice Error: {e}]{Style.RESET_ALL}")
            return None

    def listen_continuous(
        self,
        callback_fn: Callable[[str], None],
        wake_word: Optional[str] = None,
    ) -> None:
        """
        Continuous ambient loop: listens for speech, verifies wake-word,
        and passes the extracted command into callback_fn.
        :param callback_fn: Function to receive the transcribed user command
        :param wake_word: Wake-word trigger phrase (defaults to configured wake_word)
        """
        wake_phrase = (wake_word or self.wake_word).strip().lower()
        self._is_continuous_listening = True

        print(f"\n{Fore.GREEN}================================================================{Style.RESET_ALL}")
        print(f"{Fore.GREEN} Ambient Voice Mode Active | Wake Word: '{wake_phrase.title()}'{Style.RESET_ALL}")
        print(f"{Fore.LIGHTBLACK_EX} Speak naturally or say '{wake_phrase.title()}' to trigger actions. Press Ctrl+C to stop.{Style.RESET_ALL}")
        print(f"{Fore.GREEN}================================================================{Style.RESET_ALL}\n")

        while self._is_continuous_listening:
            try:
                spoken = self.listen_once()
                if not spoken:
                    continue

                spoken_lower = spoken.lower()

                # Check for wake word in spoken phrase
                if wake_phrase in spoken_lower:
                    idx = spoken_lower.index(wake_phrase) + len(wake_phrase)
                    command = spoken[idx:].strip(" ,.!?")
                    if not command:
                        self.speak("Yes, how can I assist you?", non_blocking=False)
                        continue
                else:
                    # In continuous voice mode, process whole phrase if wake word not explicitly required
                    command = spoken.strip()

                if command:
                    print(f"{Fore.CYAN}User (Spoken) > {Style.RESET_ALL}{command}")
                    callback_fn(command)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{Fore.RED}[Ambient voice error: {e}]{Style.RESET_ALL}")
                time.sleep(0.5)

        self._is_continuous_listening = False

    def stop_listening(self) -> None:
        """Signal continuous listening loop to exit."""
        self._is_continuous_listening = False


# Default singleton instance
voice_manager = VoiceManager()
