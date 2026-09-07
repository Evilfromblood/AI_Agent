# JARVIS Local Desktop Assistant (Phase 1)

A modular, local "JARVIS"-style desktop assistant in Python designed for Windows and Linux systems. It runs entirely on your machine via Ollama, targeting `gemma4:latest` (with automatic fallback to `gemma4:12b`, `gemma3:4b`, and `gemma3:12b`), and operates via both structured tool-calling and a JSON ReAct reasoning loop (`Thought` -> `Action` -> `Action Input` -> `Observation` -> `Final Answer`).

---

## Capabilities & Architecture

```
jolly-hawking/
├── config.py                 # Central Pydantic configuration & defaults
├── main.py                   # CLI REPL & command dispatcher
├── requirements.txt          # Python dependencies
├── agent/
│   ├── llm_client.py         # Ollama connector with model resolution & fallback
│   ├── prompts.py            # JARVIS persona & ReAct system instructions
│   ├── react_parser.py       # Robust JSON ReAct parser with balanced bracket extraction
│   └── core.py               # Orchestrator supporting 'react' and 'native' tool modes
├── tools/
│   ├── registry.py           # Tool decorator, JSON Schema generator, and executor
│   ├── guardrails.py         # Human-in-the-loop safety authorization for destructive actions
│   ├── file_tools.py         # list_directory, read_file, write_file, search_files, run_terminal_command
│   ├── scraper_tools.py      # scrape_page_content, extract_links (clean markdown output)
│   └── browser_tools.py      # Singleton BrowserController, Selenium Chrome driver, live DOM scraping
├── voice/
│   └── voice_input.py        # Speech-to-text handler with graceful degradation
└── tests/
    ├── test_file_tools.py    # Unit tests for file ops & safety guardrails
    ├── test_scraper_tools.py # Unit tests for web scraping & link extraction
    ├── test_browser_tools.py # Unit tests for BrowserController & Selenium
    └── test_agent_react.py   # Unit tests for ReAct parser, prompt, & agent core
```

---

## Roadmap Alignment (Phase 1)

The assistant strictly implements the 4-stage incremental capability development roadmap:

1. **Core Agent Setup (No tools)**
   - Connects to local Ollama (`http://localhost:11434`) targeting `gemma4:latest`.
   - Probes available models and tests basic conversational identity.
2. **Discrete Capabilities**
   - Read-only file operations: `list_directory`, `read_file`, `search_files`.
   - Web intelligence: `scrape_page_content` and `extract_links` with boilerplate stripping.
3. **Complex Automation**
   - Guarded file writes: `write_file` and `run_terminal_command` with interactive authorization (`Authorize? [y/N]: `) for destructive commands or file overwrites.
   - Headless/headful browser automation: `BrowserController` with `selenium` and `webdriver-manager`, dynamic live DOM extraction into `BeautifulSoup`.
4. **Validation & Feedback**
   - Complete test suite (`20/20` tests passing).
   - End-to-end task execution in both ReAct and native tool-calling modes.

---

## Setup & Quick Start

### 1. Requirements
- Python 3.10+ (tested on Python 3.14)
- [Ollama](https://ollama.com/) running locally with `gemma4:latest` (or `gemma4:12b`, `gemma3:4b`)
- Google Chrome browser (for Selenium automation)

### 2. Installation
```powershell
pip install -r requirements.txt
```

### 3. Check System Status
Verify Ollama connectivity, model availability, and tool registration:
```powershell
python main.py --status
```

### 4. Run the Interactive Assistant
Start the interactive REPL:
```powershell
python main.py
```

### 5. CLI Flags & Options
- `--mode react` (default): Uses the ReAct loop (`Thought` -> `Action` -> `Action Input` -> `Observation` -> `Final Answer`).
- `--mode native`: Uses Ollama's native tool-calling API.
- `--model gemma4:latest`: Explicitly select an LLM model.
- `--host http://localhost:11434`: Custom Ollama endpoint.
- `--status`: Print connection status and exit.
- `--demo`: Run an automated test demonstration of core capabilities.

---

## Interactive REPL Commands
- `/help` - Show available commands
- `/tools` - View all registered tools and parameter schemas
- `/status` - View current Ollama status and active model
- `/model [name]` - Switch active model
- `/mode [react|native]` - Switch between ReAct and native tool loop
- `/clear` - Clear conversation history
- `/voice` - Activate microphone input (if audio hardware is present)
- `/exit` or `/quit` - Clean up browser instances and exit

---

## Safety & Guardrails
Destructive terminal commands (`rm`, `del`, `format`, `shutdown`, system directory writes, or overwriting non-empty files) intercept execution and request confirmation:
```
============================================================
 [!] SAFETY GUARD TRIGGERED
 Reason: Existing file 'data.txt' will be overwritten and truncated.
 Action: Overwrite data.txt
============================================================
Authorize? [y/N]:
```

---

## Running Automated Tests
```powershell
pytest tests/ -v
```
All 20 test cases cover file operations, safety interception, web scraping, browser automation, and ReAct parsing.
