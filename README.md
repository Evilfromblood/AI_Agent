# Local-First Desktop AI Agent

A modular desktop AI agent for Windows and Linux that combines a **local LLM**, optional **cloud fallback**, structured tool execution, persistent memory, browser automation, and screen-aware GUI automation.

The project is designed around a simple principle: the language model plans; explicit tools perform actions; safety guardrails sit between the model and potentially destructive operations.

## Architecture

```text
User
  ↓
Agent Orchestrator
  ↓
Local LLM ──────────────── Optional Cloud Co-Pilot
  ↓
Planning / Tool Selection
  ↓
Policy & Safety Guardrails
  ↓
Tool Registry
  ├── Filesystem
  ├── Terminal
  ├── Browser
  ├── System
  ├── GUI / Screen
  └── Voice
  ↓
Observation
  ↓
Next Action / Final Response
```

## Key capabilities

- Local-first LLM execution through Ollama
- Optional online model fallback for tool-failure diagnosis
- Structured ReAct-style multi-step execution
- Native tool-calling execution mode
- Central tool registry and schema generation
- Persistent contextual memory
- Browser automation with Selenium
- Desktop screenshot capture and screen perception
- Mouse, keyboard and system-hotkey automation
- Human confirmation for destructive operations
- PyAutoGUI fail-safe behavior
- System telemetry and application launching
- Voice-input support with graceful dependency/hardware fallback

## Safety model

Desktop automation can cause real side effects, so the project treats tool execution as a separate policy boundary.

Examples of controls include:

- explicit confirmation for dangerous hotkeys
- coordinate bounds checking before mouse actions
- PyAutoGUI fail-safe mode
- guarded text entry
- bounded scraper payloads
- consecutive tool-failure tracking
- optional cloud escalation only after configured failure thresholds

The safety layer is intentionally independent of the model's natural-language reasoning.

## Project structure

```text
AI_Agent/
├── main.py
├── config.py
├── requirements.txt
├── agent/
│   ├── core.py
│   ├── llm_client.py
│   ├── prompts.py
│   └── react_parser.py
├── memory/
│   └── memory_store.py
├── tools/
│   ├── registry.py
│   ├── guardrails.py
│   ├── file_tools.py
│   ├── scraper_tools.py
│   ├── browser_tools.py
│   ├── system_tools.py
│   └── gui_tools.py
├── voice/
│   └── voice_input.py
└── tests/
    ├── test_file_tools.py
    ├── test_scraper_tools.py
    ├── test_browser_tools.py
    ├── test_system_tools.py
    ├── test_gui_tools.py
    └── test_agent_react.py
```

## Execution modes

### ReAct mode

The agent iteratively processes:

```text
Plan → Critique → Action → Observation → ... → Final Answer
```

Tool observations are fed back into the execution trajectory so the agent can adapt to failures and changing state.

### Native tool-calling mode

When supported by the local model, the agent can use structured tool calls directly instead of parsing textual Action blocks.

## Installation

```powershell
pip install -r requirements.txt
```

For optional cloud-assisted diagnosis and vision capabilities, configure the required API key through an environment variable rather than committing credentials:

```powershell
$env:GEMINI_API_KEY="your-api-key"
```

## Run

Check system status:

```powershell
python main.py --status
```

Start the interactive assistant:

```powershell
python main.py
```

Run the test suite:

```powershell
pytest tests/ -v
```

## Engineering decisions

**Local-first:** core interaction should remain usable without sending every request to a cloud service.

**Explicit tools:** filesystem, browser and desktop operations are implemented as typed tool boundaries rather than arbitrary model-generated shell commands.

**Guardrails outside the prompt:** safety checks are enforced in executable code so they do not depend solely on model compliance.

**Two execution paths:** ReAct parsing makes the agent compatible with models that emit structured text, while native tool calling provides a cleaner path when the model supports it.

**Failure escalation:** repeated tool failures can trigger an optional cloud co-pilot for diagnosis instead of blindly retrying the same action.

## Testing

Tests cover the tool registry, filesystem operations, scraping, browser integration, system utilities, GUI automation, vision-related behavior, and the agent's ReAct execution path.

Keep tests runnable without requiring real destructive desktop actions or committed credentials.

## Roadmap

- GitHub Actions for automated pytest runs
- stronger typed tool schemas
- end-to-end agent evaluation scenarios
- structured execution traces and replay
- configurable permission policies per tool
- improved memory retrieval and lifecycle management
- Linux/macOS-specific automation adapters
- benchmark suite for task success, latency and tool failures

## Status

Active experimental/portfolio project exploring local-first AI agents, tool orchestration, desktop automation, and safety-aware execution.
