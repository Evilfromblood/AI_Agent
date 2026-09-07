"""
Unit tests for JARVIS VoiceManager and Ambient Voice Engine (Phase 3.2).
Tests cover text sanitization, edge-tts neural synthesis, offline pyttsx3 fallback,
ambient STT transcription, and wake-word continuous listening.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from voice.voice_input import VoiceInputHandler
from voice.voice_manager import VoiceManager


def test_clean_text_for_speech_markdown_and_delimiters():
    raw = (
        "# System Report\n"
        "Here is the status:\n"
        "- File created at: `output.txt`\n"
        "- Link: [Visit Docs](https://example.com/docs)\n"
        "```python\n"
        "print('Hello World')\n"
        "```\n"
        "Raw URL: https://google.com\n"
        "**Bold text** and *italic text* and ~~strike~~\n"
        "> quoted note\n"
        "<channel|>Observation: done<end_of_turn>\n"
        "... [truncated for token budget]"
    )

    clean = VoiceManager.clean_text_for_speech(raw)

    assert "System Report" in clean
    assert "output.txt" in clean
    assert "Visit Docs" in clean
    assert "https://" not in clean
    assert "print('Hello World')" not in clean
    assert "```" not in clean
    assert "<channel|>" not in clean
    assert "<end_of_turn>" not in clean
    assert "[truncated" not in clean
    assert "**" not in clean
    assert "Bold text" in clean


def test_clean_text_for_speech_react_headers():
    raw = (
        "Thought: I need to check the CPU load.\n"
        "Plan: 1. Get stats. 2. Report.\n"
        "Critique: Scraper timed out earlier.\n"
        "Action: get_system_stats\n"
        "Action Input: {}\n"
        "Observation: CPU is at 15%.\n"
        "Final Answer: CPU usage is 15% and RAM is healthy."
    )

    clean = VoiceManager.clean_text_for_speech(raw)

    assert "Final Answer:" not in clean
    assert "Thought:" not in clean
    assert "C P U usage is 15 percent and R A M is healthy." in clean


def test_voice_manager_speak_edge_tts_mocked():
    vm = VoiceManager(tts_voice="en-US-ChristopherNeural")

    with patch("voice.voice_manager.HAS_EDGE_TTS", True), \
         patch("voice.voice_manager.HAS_PYGAME", True), \
         patch("edge_tts.Communicate") as mock_comm, \
         patch("pygame.mixer") as mock_mixer:

        # Mock async edge_tts synthesis save
        mock_comm_instance = MagicMock()
        mock_comm_instance.save = AsyncMock()
        mock_comm.return_value = mock_comm_instance

        # Mock pygame mixer state
        mock_mixer.get_init.return_value = True
        mock_mixer.music.get_busy.side_effect = [True, False]

        with patch.object(vm, "_speak_edge_tts", return_value=True) as mock_edge_speak:
            vm.speak("Hello sir, all systems operational.", non_blocking=False)
            mock_edge_speak.assert_called_once_with("Hello sir, all systems operational.")


def test_voice_manager_speak_offline_fallback():
    vm = VoiceManager()

    with patch.object(vm, "_speak_edge_tts", return_value=False), \
         patch.object(vm, "_speak_pyttsx3") as mock_pyttsx3:

        vm.speak("Testing offline fallback speech.", non_blocking=False)
        mock_pyttsx3.assert_called_once_with("Testing offline fallback speech.")


def test_voice_manager_pyttsx3_direct():
    vm = VoiceManager()

    with patch("voice.voice_manager.HAS_PYTTSX3", True), \
         patch("pyttsx3.init") as mock_init:
        mock_engine = MagicMock()
        mock_init.return_value = mock_engine

        result = vm._speak_pyttsx3("Fallback test")
        assert result is True
        mock_engine.say.assert_called_once_with("Fallback test")
        mock_engine.runAndWait.assert_called_once()


def test_voice_manager_listen_once_transcription():
    vm = VoiceManager()
    vm._stt_available = True
    mock_recognizer = MagicMock()
    mock_microphone = MagicMock()
    mock_recognizer.recognize_google.return_value = "open calculator"

    vm._recognizer = mock_recognizer
    vm._microphone = mock_microphone

    result = vm.listen_once(timeout=3, phrase_time_limit=5)
    assert result == "open calculator"
    mock_recognizer.adjust_for_ambient_noise.assert_called_once()
    mock_recognizer.listen.assert_called_once()


def test_voice_manager_listen_once_errors():
    import speech_recognition as sr
    vm = VoiceManager()
    vm._stt_available = True

    # 1. Timeout error
    mock_recognizer = MagicMock()
    mock_recognizer.listen.side_effect = sr.WaitTimeoutError()
    vm._recognizer = mock_recognizer
    vm._microphone = MagicMock()

    assert vm.listen_once() == ""

    # 2. Unknown value error
    mock_recognizer.listen.side_effect = None
    mock_recognizer.recognize_google.side_effect = sr.UnknownValueError()
    assert vm.listen_once() == ""


def test_clean_text_for_speech_symbols_and_acronyms():
    raw = "CPU load is 15% & RAM usage is 50% @ 3.2 GHz"
    clean = VoiceManager.clean_text_for_speech(raw)

    assert "C P U" in clean
    assert "percent" in clean
    assert " and " in clean
    assert "R A M" in clean
    assert " at " in clean


def test_voice_manager_listen_continuous_wake_word():
    vm = VoiceManager(wake_word="hey jarvis")
    # Simulate: 1. Wake word phrase, 2. Stop listening
    call_results = ["Hey Jarvis, check my CPU stats", None]

    def mock_listen_once():
        if call_results:
            val = call_results.pop(0)
            if not call_results:
                vm.stop_listening()
            return val
        return None

    vm.listen_once = mock_listen_once
    received_commands = []

    def mock_callback(cmd: str):
        received_commands.append(cmd)

    vm.listen_continuous(callback_fn=mock_callback)

    assert len(received_commands) == 1
    assert "check my cpu stats" in received_commands[0].lower()


def test_voice_input_handler_backward_compatibility():
    mock_vm = MagicMock(spec=VoiceManager)
    mock_vm.is_stt_available = True
    mock_vm.listen_once.return_value = "hello jarvis"

    handler = VoiceInputHandler(manager=mock_vm)
    assert handler.is_available is True
    res = handler.listen_and_transcribe(timeout=4, phrase_time_limit=8)
    assert res == "hello jarvis"
    mock_vm.listen_once.assert_called_once_with(timeout=4, phrase_time_limit=8)
