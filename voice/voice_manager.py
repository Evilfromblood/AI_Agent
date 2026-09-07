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
from typing import Callable, List, Optional, Union

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

try:
    import io
    import sounddevice as sd
    import numpy as np
    import scipy.io.wavfile as wav
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False


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
            except Exception:
                self._recognizer = None

            try:
                self._microphone = sr.Microphone()
                self._stt_available = True
            except Exception:
                self._microphone = None
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
        """Return True if speech recognition and an audio recording backend (Microphone or sounddevice) are available."""
        if not HAS_SR:
            return False
        has_sr_mic = (self._stt_available and self._recognizer is not None and self._microphone is not None)
        return has_sr_mic or HAS_SOUNDDEVICE

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

        # Convert raw symbols into readable conversational forms
        symbol_replacements = [
            (r"\s*&\s*", " and "),
            (r"\s*%\s*", " percent "),
            (r"\s*@\s*", " at "),
            (r"\s*\+\s*", " plus "),
            (r"\s*!=\s*", " not equal to "),
            (r"\s*==\s*", " equals "),
            (r"\s*>=\s*", " greater than or equal to "),
            (r"\s*<=\s*", " less than or equal to "),
            (r"\s*->\s*", " leads to "),
        ]
        for pattern, replacement in symbol_replacements:
            cleaned = re.sub(pattern, replacement, cleaned)

        # Expand common technical acronyms for natural conversational pronunciation
        acronym_replacements = [
            (r"\bCPU\b", "C P U"),
            (r"\bRAM\b", "R A M"),
            (r"\bGPU\b", "G P U"),
            (r"\bAPI\b", "A P I"),
            (r"\bURL\b", "U R L"),
            (r"\bTTS\b", "T T S"),
            (r"\bSTT\b", "S T T"),
            (r"\bDOM\b", "Dom"),
            (r"\bOS\b", "O S"),
        ]
        for pattern, replacement in acronym_replacements:
            cleaned = re.sub(pattern, replacement, cleaned)

        # Normalize multiple spaces and line breaks
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    def speak(
        self,
        text: str,
        blocking: bool = False,
        non_blocking: Optional[bool] = None,
    ) -> None:
        """
        Synthesize speech and play audio asynchronously or synchronously.
        Attempts edge-tts (Azure neural voice) streaming via pygame.
        Gracefully falls back to offline pyttsx3 on error or disconnection.
        :param text: Text to synthesize and speak
        :param blocking: If True, blocks until audio finishes playing
        :param non_blocking: Deprecated alias for not blocking
        """
        clean_text = self.clean_text_for_speech(text)
        if not clean_text:
            return

        should_block = blocking if non_blocking is None else not non_blocking

        if not should_block:
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
    ) -> str:
        """
        Listen to microphone input once and transcribe speech to text.
        :param timeout: Silence duration limit before giving up (seconds)
        :param phrase_time_limit: Max continuous duration for a single phrase
        :return: Clean transcribed string, or empty string on silence/error
        """
        timeout = timeout or self.listen_timeout
        phrase_time_limit = phrase_time_limit or self.phrase_time_limit

        if not self.is_stt_available:
            print(
                f"{Fore.YELLOW}[Voice] Speech recognition hardware or audio capture libraries are unavailable.\n"
                f"        Please enter commands directly via keyboard.{Style.RESET_ALL}"
            )
            return ""

        # 1. First attempt: speech_recognition.Microphone if available
        if self._microphone is not None and self._stt_available and self._recognizer is not None:
            try:
                print(f"\n{Fore.CYAN}[Listening...] Speak now.{Style.RESET_ALL}")
                with self._microphone as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.8)
                    audio = self._recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )

                print(f"{Fore.CYAN}[Transcribing voice...]{Style.RESET_ALL}")
                transcription = self._recognizer.recognize_google(audio)
                cleaned = transcription.strip() if transcription else ""
                if cleaned:
                    print(f"{Fore.GREEN}[Voice Transcribed]: \"{cleaned}\"{Style.RESET_ALL}")
                return cleaned

            except sr.WaitTimeoutError:
                print(f"{Fore.LIGHTBLACK_EX}[Voice: Listening timed out (no speech detected)]{Style.RESET_ALL}")
                return ""
            except sr.UnknownValueError:
                print(f"{Fore.LIGHTBLACK_EX}[Voice: Speech could not be understood]{Style.RESET_ALL}")
                return ""
            except Exception as e:
                # If microphone failed (PyAudio or device failure), fall back to sounddevice if available
                if not HAS_SOUNDDEVICE:
                    print(f"{Fore.RED}[Voice Error: {e}]{Style.RESET_ALL}")
                    return ""

        # 2. Fallback: recording directly with sounddevice & numpy
        if HAS_SOUNDDEVICE:
            return self._listen_with_sounddevice(duration=phrase_time_limit or 5)

        return ""

    def _listen_with_sounddevice(self, duration: int = 5, fs: int = 16000) -> str:
        """
        Record audio directly using sounddevice and transcribe using Recognizer and AudioFile.
        """
        try:
            import io
            import numpy as np
            import scipy.io.wavfile as wav
            import sounddevice as sd
            import speech_recognition as sr

            print(f"\n{Fore.CYAN}[Listening... speak now]{Style.RESET_ALL}")
            audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="int16")
            sd.wait()

            byte_io = io.BytesIO()
            wav.write(byte_io, fs, audio_data)
            byte_io.seek(0)

            r = self._recognizer or sr.Recognizer()
            with sr.AudioFile(byte_io) as source:
                audio = r.record(source)

            print(f"{Fore.CYAN}[Transcribing voice...]{Style.RESET_ALL}")
            text = r.recognize_google(audio)
            cleaned = text.strip() if text else ""
            if cleaned:
                print(f"{Fore.GREEN}[Voice Transcribed]: \"{cleaned}\"{Style.RESET_ALL}")
            return cleaned

        except Exception as e:
            err_name = type(e).__name__
            if "UnknownValueError" in err_name:
                print(f"{Fore.LIGHTBLACK_EX}[Voice: Speech could not be understood (silence or low volume)]{Style.RESET_ALL}")
            elif "RequestError" in err_name:
                print(f"{Fore.RED}[Voice Error: Google Speech Recognition connection issue: {e}]{Style.RESET_ALL}")
            elif "WaitTimeoutError" in err_name:
                print(f"{Fore.LIGHTBLACK_EX}[Voice: Listening timed out]{Style.RESET_ALL}")
            else:
                print(f"{Fore.LIGHTBLACK_EX}[Voice: {err_name} - {e}]{Style.RESET_ALL}")
            return ""

    def listen_continuous(
        self,
        callback_fn: Callable[[str], None],
        wake_words: Optional[Union[list[str], str]] = None,
    ) -> None:
        """
        Continuous ambient loop: listens for speech, verifies wake-word,
        and passes the extracted command into callback_fn.
        :param callback_fn: Function to receive the transcribed user command
        :param wake_words: List of trigger phrases (e.g. ['hey jarvis', 'jarvis'])
        """
        if wake_words is None:
            wake_phrases = ["hey jarvis", "jarvis"]
        elif isinstance(wake_words, str):
            wake_phrases = [wake_words.strip().lower()]
        else:
            wake_phrases = [w.strip().lower() for w in wake_words]

        primary_wake = wake_phrases[0]
        self._is_continuous_listening = True

        print(f"\n{Fore.GREEN}================================================================{Style.RESET_ALL}")
        print(f"{Fore.GREEN} Ambient Voice Mode Active | Wake Words: {', '.join(repr(w) for w in wake_phrases)}{Style.RESET_ALL}")
        print(f"{Fore.LIGHTBLACK_EX} Speak naturally or say '{primary_wake.title()}' to trigger actions. Press Ctrl+C to stop.{Style.RESET_ALL}")
        print(f"{Fore.GREEN}================================================================{Style.RESET_ALL}\n")

        while self._is_continuous_listening:
            try:
                spoken = self.listen_once()
                if not spoken:
                    continue

                spoken_lower = spoken.lower()
                command = None

                # Check each wake word in spoken phrase
                matched_wake = None
                for w in wake_phrases:
                    if w in spoken_lower:
                        matched_wake = w
                        break

                if matched_wake:
                    idx = spoken_lower.index(matched_wake) + len(matched_wake)
                    command = spoken[idx:].strip(" ,.!?")
                    if not command:
                        self.speak("Yes, how can I assist you?", blocking=True)
                        continue
                else:
                    # In continuous voice mode, process full phrase if wake word omitted
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
