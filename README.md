# JARVIS Desktop Assistant (Phase 1 & Phase 2)

A modular, local-first "JARVIS"-style desktop assistant in Python designed for Windows and Linux. It pairs a **Primary Local Brain** (`gemma4:latest` via Ollama) with an **Online Supporting Brain** (Google Gemini 2.5 Flash via official `google-genai`), autonomous self-thinking (`Plan` -> `Critique` -> `Action`), stealth browser automation, and system telemetry tools.

---

## Phase 2 Architecture: Hybrid Co-Pilot & Self-Thinking Engine

```
                                  +-------------------+
                                  |   User Prompt     |
                                  +---------+---------+
                                            |
                                            v
                              +---------------------------+
                              |   Dual-Brain Router       |
                              |  (Model Tier Coordinator) |
                              +-------------+-------------+
                                            |
             +------------------------------+------------------------------+
             |                                                             |
             v                                                             v
+---------------------------+                                 +---------------------------+
| Primary Local Brain       |                                 | Online Supporting Brain   |
| Gemma 4 (Local Ollama)    |                                 | Gemini 2.5 Flash          |
| Fast, zero-cost, local PC |                                 | (High context, heavy code,|
| operations & scrapers     |                                 | diagnostics & synthesis)  |
+-------------+-------------+                                 +-------------+-------------+
             |                                                             |
             +------------------------------+------------------------------+
                                            |
                                            v
                             +-----------------------------+
                             |    Self-Thinking Engine     |
                             |  - Plan & Decompose Tasks   |
                             |  - Critique Tool Result     |
                             |  - Auto-Escalate Failures   |
                             +--------------+--------------+
                                            |
                                            v
                             +-----------------------------+
                             |     Phase 2 Toolset         |
                             |  - System telemetry (psutil)|
                             |  - App Launcher             |
                             |  - Stealth Selenium         |
                             |  - Bounded Scrapers         |
                             +-----------------------------+
```

---

## Directory & File Structure

```
jolly-hawking/
├── config.py                 # Pydantic configuration & Gemini settings
├── main.py                   # CLI REPL & command dispatcher
├── requirements.txt          # Python dependencies (Ollama, Gemini, Selenium, Psutil, etc.)
├── agent/
│   ├── llm_client.py         # Local Ollama + GeminiClientWrapper dual-brain router
│   ├── prompts.py            # JARVIS persona & self-reflecting ReAct instructions (Plan/Critique)
│   ├── react_parser.py       # Balanced JSON parser extracting Thought, Plan, Critique, Action
│   └── core.py               # Orchestrator with consecutive tool failure escalation
├── tools/
│   ├── registry.py           # Tool decorator, JSON Schema generator, and executor
│   ├── guardrails.py         # Human-in-the-loop safety authorization for destructive actions
│   ├── file_tools.py         # list_directory, read_file, write_file, search_files, run_terminal_command
│   ├── scraper_tools.py      # scrape_page_content (bounded payload), extract_links
│   ├── browser_tools.py      # Singleton BrowserController, stealth Chrome, JS click fallback, wait_for_page_load
│   └── system_tools.py       # get_system_stats, launch_application
├── voice/
│   └── voice_input.py        # Speech-to-text handler with graceful degradation
└── tests/
    ├── test_file_tools.py    # Tests for file operations & safety guardrails
    ├── test_scraper_tools.py # Tests for web scraping & payload truncation
    ├── test_browser_tools.py # Tests for BrowserController & Selenium
    ├── test_system_tools.py  # Tests for system telemetry & app launching
    └── test_agent_react.py   # Tests for ReAct parser, Plan/Critique, & Gemini escalation
```

---

## Key Capabilities

1. **Hybrid Dual-Brain Coordinator (`agent/llm_client.py`)**:
   - **Local Driver**: `gemma4:latest` handles day-to-day commands with zero latency and complete privacy.
   - **Cloud Co-Pilot**: Google Gemini 2.5 Flash via `google-genai`. If local actions fail consecutively or if complex diagnosis is needed, the assistant automatically routes context to Gemini.
2. **Autonomous "Self-Thinking" Loop (`agent/prompts.py`, `agent/react_parser.py`, `agent/core.py`)**:
   - **`Plan:`** 1-3 step roadmap before taking actions on complex objectives.
   - **`Critique:`** Evaluates previous observation to diagnose failures or anomalies before choosing the next action.
   - **Failure Auto-Escalation**: Consecutive failures on any tool automatically query the cloud co-pilot for a recovery strategy.
3. **Stealth Browser Engine (`tools/browser_tools.py`)**:
   - Injects anti-detection flags (`--disable-blink-features=AutomationControlled`, desktop user-agent, `excludeSwitches=["enable-automation"]`).
   - JavaScript click fallback (`driver.execute_script("arguments[0].click();", elem)`) when click is intercepted by overlays.
   - `wait_for_page_load()` for dynamic single-page applications.
4. **System Telemetry & App Control (`tools/system_tools.py`)**:
   - `get_system_stats()`: Live CPU usage %, core count, RAM utilization, and disk storage metrics via `psutil`.
   - `launch_application(app_name)`: Launches approved desktop utilities (`notepad`, `calc`, `taskmgr`, `explorer`, `code`).

---

## Setup & Quick Start

### 1. Installation
```powershell
pip install -r requirements.txt
```

### 2. Configure Cloud Co-Pilot (Optional)
Set your Google Gemini API key to activate the cloud supporting brain:
```powershell
$env:GEMINI_API_KEY="your-gemini-api-key"
```

### 3. Check System Status
```powershell
python main.py --status
```

### 4. Interactive REPL
```powershell
python main.py
```

### REPL Commands
- `/help` - Show available commands
- `/tools` - List all registered tools (15 tools ready)
- `/status` - Check Ollama, active model, and Gemini co-pilot status
- `/copilot [prompt]` - Directly query the online Gemini co-pilot
- `/model [name]` - Switch active local model
- `/mode [react|native]` - Toggle execution mode
- `/clear` - Reset conversation history and error counters
- `/voice` - Activate voice recognition
- `/exit` - Clean up browser and shut down

---

## Running Automated Tests
```powershell
pytest tests/ -v
```
All **29/29** unit tests pass cleanly, covering file tools, guardrails, scraping, browser automation, system telemetry, and the self-reflecting ReAct loop.
