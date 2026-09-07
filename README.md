# JARVIS Desktop Assistant (Phases 1, 2 & 3.1)

A modular, local-first "JARVIS"-style desktop assistant in Python designed for Windows and Linux. It pairs a **Primary Local Brain** (`gemma4:latest` via Ollama) with an **Online Supporting Brain** (Google Gemini 2.5 Flash via official `google-genai`), autonomous self-thinking (`Plan` -> `Critique` -> `Action`), stealth browser automation, system telemetry, and **Desktop GUI Automation & Screen Perception**.

---

## Architectural Overview

```
                          +-------------------------+
                          |   User Voice / Text     |
                          +------------+------------+
                                       |
                                       v
                          +-------------------------+
                          |   Dual-Brain Router     |
                          | (Local Gemma 4 / Gemini)|
                          +------------+------------+
                                       |
                                       v
                          +-------------------------+
                          |  Self-Thinking Engine   |
                          |  Plan, Critique, Adapt  |
                          +------------+------------+
                                       |
        +------------------------------+------------------------------+
        |                              |                              |
        v                              v                              v
+---------------+              +---------------+              +---------------+
| System Tools  |              | Browser Tools |              | GUI & Vision  |
| - psutil      |              | - Stealth Chrome             | - mss Screen  |
| - App Control |              | - JS Click Fallback          | - PyAutoGUI   |
| - File Ops    |              | - Live DOM Soup              | - Gemini 2.5V |
+---------------+              +---------------+              +---------------+
```

---

## Directory & File Structure

```
jolly-hawking/
├── config.py                 # Pydantic configuration (models, timeouts, hotkey guardrails)
├── main.py                   # Interactive CLI REPL with /help, /tools, /copilot, /voice
├── requirements.txt          # Dependencies (ollama, google-genai, selenium, psutil, pyautogui, mss, pillow)
├── agent/
│   ├── llm_client.py         # Dual-brain router: Ollama (gemma4) + GeminiClientWrapper (gemini-2.5-flash)
│   ├── prompts.py            # JARVIS persona & self-reflecting ReAct loop (Plan & Critique)
│   ├── react_parser.py       # Balanced JSON parser with token stripping (<channel|>, <end_of_turn>)
│   └── core.py               # Orchestrator with consecutive tool failure escalation
├── tools/
│   ├── registry.py           # Central tool decorator, schema generator, and executor
│   ├── guardrails.py         # Human-in-the-loop confirmation for destructive commands & hotkeys
│   ├── file_tools.py         # list_directory, read_file, write_file, search_files, run_terminal_command
│   ├── scraper_tools.py      # scrape_page_content (bounded token budget), extract_links
│   ├── browser_tools.py      # BrowserController: stealth Chrome, JS click fallback, wait_for_page_load
│   ├── system_tools.py       # get_system_stats (CPU/RAM/Disk), launch_application
│   └── gui_tools.py          # take_screenshot, analyze_screen_with_vision, click_screen_coordinate, type_screen_text, send_system_hotkey
├── voice/
│   └── voice_input.py        # Audio capture handler with graceful library/hardware fallback
└── tests/
    ├── test_file_tools.py    # Unit tests for file ops & safety guardrails
    ├── test_scraper_tools.py # Unit tests for web scraping & payload truncation
    ├── test_browser_tools.py # Unit tests for BrowserController & Selenium
    ├── test_system_tools.py  # Unit tests for hardware stats & application launcher
    ├── test_gui_tools.py     # Unit tests for screen capture, PyAutoGUI, hotkeys, & vision grounding
    └── test_agent_react.py   # Unit tests for ReAct parser, Plan/Critique, & Gemini escalation
```

---

## Phase 3.1 Capabilities: Desktop GUI Automation & Screen Perception

1. **High-Speed Screen Capture (`mss` + `pillow`)**:
   - `take_screenshot(filename, region)`: Multi-monitor hardware-accelerated screenshot capture with optional bounding box cropping.
2. **Vision Grounding with Gemini 2.5 Flash**:
   - `analyze_screen_with_vision(prompt, image_path)`: Uses `google-genai` to analyze desktop screenshots, detect active windows, extract text from dialogs, and estimate pixel coordinates `(x, y)` for buttons and UI elements.
3. **Safe Mouse & Keyboard Control (`pyautogui`)**:
   - `click_screen_coordinate(x, y, clicks, button)`: Mouse positioning with strict resolution boundary verification.
   - `type_screen_text(text, press_enter, interval)`: Sequential character typing into active windows, gated by guardrails against malicious script injection.
   - `send_system_hotkey(keys)`: Dispatches OS shortcuts (e.g. `["win", "r"]`, `["ctrl", "s"]`).
4. **Safety Guardrails & Fail-Safe Protection**:
   - `pyautogui.FAILSAFE = True` enabled globally: Slamming cursor into any screen corner immediately aborts running automation.
   - Dangerous hotkeys (`alt+f4`, `win+l`, `ctrl+alt+del`, `win+x`) require explicit human confirmation (`Authorize? [y/N]: `).

---

## Quick Start & Verification

### 1. Installation
```powershell
pip install -r requirements.txt
```

### 2. Configure Cloud Co-Pilot & Vision (Optional)
```powershell
$env:GEMINI_API_KEY="your-gemini-api-key"
```

### 3. Check System Status
```powershell
python main.py --status
```

### 4. Run Interactive Assistant
```powershell
python main.py
```

### 5. Automated Tests
```powershell
pytest tests/ -v
```
All **39/39** tests pass across all subsystems.
