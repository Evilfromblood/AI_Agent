"""
JARVIS Desktop Assistant - Main Entrypoint and Interactive REPL.
Phase 1: Local Ollama / Gemma 4 integration, tool registry, and safety guardrails.
"""

import argparse
import sys
from colorama import Fore, Style, init

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tools  # Automatically registers file, scraper, and browser tools
from agent.core import JarvisAgent
from agent.llm_client import LLMClient
from config import config
from daemon import HardwareSentry, TaskScheduler
from tools.browser_tools import browser_controller
from tools.registry import registry
from voice.voice_input import VoiceInputHandler
from voice.voice_manager import VoiceManager, voice_manager

init(autoreset=True)

BANNER = f"""{Fore.CYAN}
================================================================
     _   _   ___ __   __ ___  ___ 
  _ | | /_\\ | _ \\\\ \\ / /|_ _|/ __|
 | || |/ _ \\|   / \\ V /  | | \\__ \\
  \\__//_/ \\_\\_|_\\  \\_/  |___||___/
{Fore.LIGHTBLACK_EX} Local Desktop Assistant | Phase 4: Floating HUD & System Tray Hub{Fore.CYAN}
================================================================{Style.RESET_ALL}
"""


def print_status(llm: LLMClient, agent_mode: str) -> None:
    """Print connection and system configuration status."""
    connected = llm.check_connection()
    status_color = Fore.GREEN if connected else Fore.RED
    status_text = "CONNECTED" if connected else "OFFLINE"

    gemini_ready = llm.gemini.is_available
    gemini_color = Fore.GREEN if gemini_ready else Fore.YELLOW
    gemini_status = f"READY ({config.gemini_model})" if gemini_ready else "NOT CONFIGURED (set GEMINI_API_KEY)"

    print("\n" + "-" * 60)
    print(f" Ollama Endpoint  : {config.ollama_base_url} [{status_color}{status_text}{Style.RESET_ALL}]")
    if connected:
        active_model = llm.resolve_model()
        available = llm.list_models()
        print(f" Primary Brain    : {Fore.YELLOW}{active_model}{Style.RESET_ALL} (Local Ollama)")
        print(f" Available Models : {', '.join(available) if available else 'None detected'}")
    else:
        print(f" Primary Brain    : {Fore.YELLOW}{config.target_model}{Style.RESET_ALL} (Ollama offline)")
    print(f" Online Co-Pilot  : [{gemini_color}{gemini_status}{Style.RESET_ALL}]")
    print(f" Execution Mode   : {Fore.MAGENTA}{agent_mode.upper()}{Style.RESET_ALL} (Self-Thinking ReAct)")
    print(f" Registered Tools : {len(registry.list_tool_names())} tools ready")
    print("-" * 60 + "\n")


def print_help() -> None:
    """Print available REPL commands."""
    print(f"\n{Fore.CYAN}Available Commands:{Style.RESET_ALL}")
    print("  /help         - Display this help message")
    print("  /tools        - List all registered tools and their parameters")
    print("  /status       - Show Ollama connection and active model status")
    print("  /model [name] - Switch active model (or view available)")
    print("  /mode [type]  - Switch execution mode ('react' or 'native')")
    print("  /clear        - Clear conversation history")
    print("  /voice        - Trigger voice input recognition")
    print("  /speak [text] - Synthesize speech using neural TTS")
    print("  /copilot      - Check or invoke online Gemini co-pilot")
    print("  /exit, /quit  - Exit JARVIS\n")


def print_tools() -> None:
    """List all registered tools."""
    print(f"\n{Fore.YELLOW}Registered Assistant Tools:{Style.RESET_ALL}")
    print(registry.get_react_descriptions())
    print()


def run_demo(agent: JarvisAgent) -> None:
    """Run an automated demonstration of JARVIS capabilities."""
    print(f"\n{Fore.GREEN}=== Running JARVIS Phase 1 Capabilities Demo ==={Style.RESET_ALL}\n")

    demo_tasks = [
        "List the files and folders in the current directory.",
        "Check the contents of requirements.txt and tell me what packages are installed.",
        "Write a small welcome file named 'demo_output.txt' containing 'Hello from JARVIS Assistant!'.",
        "Read back the content of 'demo_output.txt' to confirm it was created properly.",
    ]

    for i, task in enumerate(demo_tasks, 1):
        print(f"\n{Fore.CYAN}[Demo Step {i}/{len(demo_tasks)}]{Style.RESET_ALL} Task: {task}")
        agent.run(task)

    print(f"\n{Fore.GREEN}=== Demo Complete ==={Style.RESET_ALL}\n")


def repl(agent: JarvisAgent, vm: Optional[VoiceManager] = None, voice_mode: bool = False) -> None:
    """Interactive Read-Eval-Print-Loop."""
    vm = vm or voice_manager
    print(BANNER)
    print_status(agent.llm, agent.mode)
    print(f"Type your request, use {Fore.CYAN}/help{Style.RESET_ALL} for commands, or type {Fore.CYAN}/exit{Style.RESET_ALL} to quit.\n")

    while True:
        try:
            prompt = input(f"{Fore.CYAN}User > {Style.RESET_ALL}").strip()
            if not prompt:
                continue

            # Command routing
            if prompt.startswith("/"):
                cmd_parts = prompt.split(maxsplit=1)
                cmd = cmd_parts[0].lower()
                arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

                if cmd in ("/exit", "/quit"):
                    print(f"\n{Fore.CYAN}Shutting down JARVIS. Have a good day, sir.{Style.RESET_ALL}")
                    browser_controller.close_browser()
                    vm.stop_speech()
                    sys.exit(0)
                elif cmd == "/help":
                    print_help()
                elif cmd == "/status":
                    print_status(agent.llm, agent.mode)
                elif cmd == "/tools":
                    print_tools()
                elif cmd == "/clear":
                    agent.reset()
                    print(f"{Fore.GREEN}Conversation memory cleared.{Style.RESET_ALL}")
                elif cmd == "/mode":
                    if arg in ("react", "native"):
                        agent.mode = arg
                        print(f"{Fore.GREEN}Execution mode switched to '{arg}'.{Style.RESET_ALL}")
                    else:
                        print(f"Current mode: '{agent.mode}'. Use '/mode react' or '/mode native'.")
                elif cmd == "/model":
                    if arg:
                        agent.llm.selected_model = arg
                        print(f"{Fore.GREEN}Active model set to '{arg}'.{Style.RESET_ALL}")
                    else:
                        models = agent.llm.list_models()
                        print(f"Current model: {agent.llm.resolve_model()}")
                        print(f"Available models: {', '.join(models)}")
                elif cmd == "/voice":
                    if vm.is_stt_available:
                        spoken = vm.listen_once()
                        if spoken:
                            print(f"{Fore.CYAN}User (Spoken) > {Style.RESET_ALL}{spoken}")
                            ans = agent.run(spoken)
                            if ans:
                                vm.speak(ans)
                    else:
                        print(f"{Fore.YELLOW}Voice input is unavailable on this machine. Type query directly.{Style.RESET_ALL}")
                elif cmd == "/speak":
                    if arg:
                        print(f"{Fore.MAGENTA}[JARVIS Speaking]...{Style.RESET_ALL}")
                        vm.speak(arg)
                    else:
                        print("Usage: /speak <text to say>")
                elif cmd == "/copilot":
                    if agent.llm.gemini.is_available:
                        if arg:
                            print(f"{Fore.LIGHTMAGENTA_EX}[Invoking Gemini 3.6 Flash Co-Pilot]...{Style.RESET_ALL}")
                            ans = agent.llm.chat_online([{"role": "user", "content": arg}])
                            print(f"{Fore.MAGENTA}Gemini Co-Pilot:{Style.RESET_ALL} {ans.get('content')}")
                        else:
                            print(f"{Fore.GREEN}Online Co-Pilot is active ({config.gemini_model}). Type '/copilot <prompt>' to query directly.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.YELLOW}Online Co-Pilot is not configured. Set GEMINI_API_KEY environment variable.{Style.RESET_ALL}")
                else:
                    print(f"Unknown command '{cmd}'. Type /help for options.")
                continue

            # Execute user prompt through agent
            response = agent.run(prompt)
            if voice_mode or config.voice_enabled:
                if response:
                    vm.speak(response)

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{Fore.CYAN}Session interrupted. Shutting down JARVIS.{Style.RESET_ALL}")
            browser_controller.close_browser()
            vm.stop_speech()
            break
        except Exception as e:
            print(f"\n{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")


def run_ambient_voice_mode(agent: JarvisAgent, vm: VoiceManager) -> None:
    """Continuous hands-free ambient voice loop."""
    print(BANNER)
    print_status(agent.llm, agent.mode)

    def on_voice_command(command: str):
        response = agent.run(command)
        if response:
            vm.speak(response, non_blocking=False)

    vm.listen_continuous(callback_fn=on_voice_command)


def run_hud_mode(agent: JarvisAgent, vm: VoiceManager) -> None:
    """Launch the native PySide6 translucent floating HUD and system tray daemon."""
    from ui.qt_hud import run_qt_hud

    print(BANNER)
    print_status(agent.llm, agent.mode)
    print(f"{Fore.GREEN}[HUD Mode Active] Press Ctrl+Space to toggle HUD, Esc to hide.{Style.RESET_ALL}\n")

    try:
        run_qt_hud(agent=agent, vm=vm)
    except KeyboardInterrupt:
        pass




def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(description="JARVIS Local Desktop Assistant")
    parser.add_argument("--mode", choices=["react", "native"], default="react", help="Tool execution mode")
    parser.add_argument("--model", type=str, default=None, help="Specific model to use")
    parser.add_argument("--host", type=str, default=None, help="Ollama API host URL")
    parser.add_argument("--status", action="store_true", help="Print system status and exit")
    parser.add_argument("--demo", action="store_true", help="Run automated capabilities demonstration")
    parser.add_argument("--voice", action="store_true", help="Start in continuous ambient voice loop mode")
    parser.add_argument("--hud", action="store_true", help="Launch in dedicated floating HUD and system tray mode")
    args = parser.parse_args()

    llm = LLMClient(host=args.host, model=args.model)
    agent = JarvisAgent(llm_client=llm, mode=args.mode)
    vm = voice_manager

    if args.status:
        print(BANNER)
        print_status(llm, agent.mode)
        sys.exit(0)

    if args.demo:
        print(BANNER)
        print_status(llm, agent.mode)
        run_demo(agent)
        sys.exit(0)

    # Initialize and start proactive background daemons
    sentry = HardwareSentry(vm=vm, voice_alert=True)
    scheduler = TaskScheduler(vm=vm, voice_alert=True)
    sentry.start()
    scheduler.start()

    try:
        if args.hud:
            run_hud_mode(agent, vm)
        elif args.voice or config.voice_enabled:
            run_ambient_voice_mode(agent, vm)
        else:
            repl(agent, vm, voice_mode=args.voice)
    finally:
        sentry.stop()
        scheduler.stop()



if __name__ == "__main__":
    main()
