"""
Core agent orchestrator for JARVIS desktop assistant.
Executes user requests using either structured ReAct loop or native Ollama tool calling.
"""

from typing import Any, Callable, Dict, List, Optional
from colorama import Fore, Style, init

from agent.llm_client import LLMClient
from agent.prompts import build_system_prompt
from agent.react_parser import ReActParser, ReActStep
from config import config
from tools.registry import registry

init(autoreset=True)

TOOL_KEYWORDS = {
    "stats",
    "screenshot",
    "notepad",
    "launch",
    "write",
    "open",
    "click",
    "type",
    "hotkey",
    "read",
}


class JarvisAgent:
    """Autonomous desktop assistant agent orchestrating tools and LLM inference."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        mode: str = "react",
        verbose: bool = True,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize JarvisAgent.
        :param llm_client: Local LLM client instance
        :param mode: Execution mode ('react' or 'native')
        :param verbose: Whether to print colored execution steps to console
        :param log_callback: Optional custom callback (channel: str, message: str) -> None
        """
        self.llm = llm_client or LLMClient()
        self.mode = mode.lower()
        self.verbose = verbose
        self.log_callback = log_callback
        self.conversation_history: List[Dict[str, Any]] = []
        self.consecutive_tool_failures: int = 0
        self.last_failed_tool: Optional[str] = None

    def _log(self, channel: str, message: str) -> None:
        """Log message with color and invoke external callback if present."""
        if self.log_callback:
            self.log_callback(channel, message)

        if not self.verbose:
            return

        if channel == "thought":
            print(f"{Fore.CYAN}Thought:{Style.RESET_ALL} {message}")
        elif channel == "plan":
            print(f"{Fore.BLUE}Plan:{Style.RESET_ALL} {message}")
        elif channel == "critique":
            print(f"{Fore.LIGHTRED_EX}Critique:{Style.RESET_ALL} {message}")
        elif channel == "action":
            print(f"{Fore.YELLOW}Action:{Style.RESET_ALL} {message}")
        elif channel == "action_input":
            print(f"{Fore.YELLOW}Action Input:{Style.RESET_ALL} {message}")
        elif channel == "observation":
            preview = message if len(message) < 500 else message[:500] + "... [truncated]"
            print(f"{Fore.GREEN}Observation:{Style.RESET_ALL}\n{preview}")
        elif channel == "final_answer":
            print(f"{Fore.MAGENTA}JARVIS:{Style.RESET_ALL}\n{message}")
        elif channel == "error":
            print(f"{Fore.RED}Error:{Style.RESET_ALL} {message}")
        elif channel == "info":
            print(f"{Fore.LIGHTMAGENTA_EX}[CO-PILOT INFO]{Style.RESET_ALL} {message}")

    def reset(self) -> None:
        """Clear conversation history and error counters."""
        self.conversation_history.clear()
        self.consecutive_tool_failures = 0
        self.last_failed_tool = None

    def run(self, user_prompt: str) -> str:
        """
        Execute user request and return final response.
        Routes to react or native tool execution loop.
        """
        if self.mode == "native":
            return self._run_native_tool_loop(user_prompt)
        return self._run_react_loop(user_prompt)

    def _run_react_loop(self, user_prompt: str) -> str:
        """
        Execute iterative ReAct loop:
        Thought -> Plan -> Critique -> Action -> Action Input -> Observation -> ... -> Final Answer
        """
        tool_descriptions = registry.get_react_descriptions()
        tool_names = registry.list_tool_names()
        system_prompt = build_system_prompt(tool_descriptions, tool_names)

        # Build trajectory for this run
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        # Include past conversation context
        for turn in self.conversation_history:
            messages.append(turn)

        messages.append({"role": "user", "content": f"Question: {user_prompt}"})

        tools_executed = 0
        intercepted_bypass = False
        prompt_lower = user_prompt.lower()
        has_tool_keyword = any(kw in prompt_lower for kw in TOOL_KEYWORDS)

        for step_idx in range(1, config.max_react_steps + 1):
            response = self.llm.chat(messages=messages, temperature=0.2)
            raw_text = response.get("content", "").strip()

            if not raw_text:
                self._log("error", "Empty response from language model.")
                break

            step: ReActStep = ReActParser.parse(raw_text)

            if step.thought:
                self._log("thought", step.thought)
            if step.plan:
                self._log("plan", step.plan)
            if step.critique:
                self._log("critique", step.critique)

            # Intercept premature final answer or direct response without tool execution
            if not step.action and tools_executed == 0 and not intercepted_bypass and has_tool_keyword:
                intercepted_bypass = True
                self._log("info", "Tool execution bypass intercepted. Re-prompting for Action block.")
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({
                    "role": "user",
                    "content": "You answered without executing required tools. Output an Action block to execute the first step.",
                })
                continue

            # Check for final answer
            if step.is_final or step.final_answer:
                final_text = step.final_answer or step.thought
                self._log("final_answer", final_text)
                self.conversation_history.append({"role": "user", "content": user_prompt})
                self.conversation_history.append({"role": "assistant", "content": final_text})
                self.consecutive_tool_failures = 0
                return final_text

            # Execute tool action
            if step.action:
                tools_executed += 1
                self._log("action", step.action)
                self._log("action_input", str(step.action_input or {}))

                if step.parse_error:
                    observation = f"Format Error: {step.parse_error}"
                else:
                    observation = registry.execute(step.action, step.action_input or {})

                self._log("observation", observation)

                # Check for failure to trigger error-critique & co-pilot escalation
                is_failure = (
                    observation.strip().lower().startswith("error")
                    or "security guardrail interception" in observation.lower()
                    or "failed to fetch" in observation.lower()
                )

                if is_failure:
                    self.consecutive_tool_failures += 1
                    self.last_failed_tool = step.action

                    # Escalate to online Gemini co-pilot if failure threshold reached
                    if (
                        self.consecutive_tool_failures >= config.consecutive_failure_threshold
                        and config.enable_online_fallback
                        and self.llm.gemini.is_available
                    ):
                        self._log(
                            "info",
                            f"Tool '{step.action}' failed {self.consecutive_tool_failures} times consecutively. "
                            f"Escalating to Gemini 3.6 Flash co-pilot for failure diagnosis and strategy...",
                        )
                        diagnosis_prompt = [
                            *messages,
                            {
                                "role": "user",
                                "content": (
                                    f"ESCALATION: Action '{step.action}' failed consecutively with observation:\n"
                                    f"{observation}\n"
                                    f"Diagnose the cause of this failure and provide a 1-sentence Critique "
                                    f"and an adjusted Plan/Action."
                                ),
                            },
                        ]
                        copilot_resp = self.llm.chat_online(diagnosis_prompt)
                        advice = copilot_resp.get("content", "").strip()
                        if advice:
                            self._log("info", f"Gemini Co-Pilot Guidance:\n{advice}")
                            messages.append(
                                {"role": "assistant", "content": f"Critique (from Co-Pilot): {advice}"}
                            )
                else:
                    self.consecutive_tool_failures = 0
                    self.last_failed_tool = None

                # Feed observation back into ReAct trajectory
                assistant_parts = []
                if step.thought:
                    assistant_parts.append(f"Thought: {step.thought}")
                if step.plan:
                    assistant_parts.append(f"Plan: {step.plan}")
                if step.critique:
                    assistant_parts.append(f"Critique: {step.critique}")
                assistant_parts.append(f"Action: {step.action}\nAction Input: {step.action_input}")

                messages.append({"role": "assistant", "content": "\n".join(assistant_parts)})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                # No action and no final answer found, treat as final text
                final_text = raw_text
                self._log("final_answer", final_text)
                self.conversation_history.append({"role": "user", "content": user_prompt})
                self.conversation_history.append({"role": "assistant", "content": final_text})
                self.consecutive_tool_failures = 0
                return final_text

        fallback_final = "Reached maximum step limit without a definitive final answer."
        self._log("final_answer", fallback_final)
        return fallback_final

    def _run_native_tool_loop(self, user_prompt: str) -> str:
        """
        Execute using Ollama's native tool-calling function signatures.
        """
        tools = registry.get_ollama_tools()
        messages = [
            {"role": "system", "content": "You are JARVIS, a helpful, precise desktop AI assistant."},
        ]
        for turn in self.conversation_history:
            messages.append(turn)

        messages.append({"role": "user", "content": user_prompt})

        for step_idx in range(1, config.max_react_steps + 1):
            response = self.llm.chat(messages=messages, tools=tools, temperature=0.2)
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            if tool_calls:
                # Append assistant tool invocation message
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })

                for call in tool_calls:
                    fn_info = call.get("function", {})
                    fn_name = fn_info.get("name", "")
                    fn_args = fn_info.get("arguments", {})

                    self._log("action", fn_name)
                    self._log("action_input", str(fn_args))

                    observation = registry.execute(fn_name, fn_args)
                    self._log("observation", observation)

                    messages.append({
                        "role": "tool",
                        "name": fn_name,
                        "content": observation,
                    })
            else:
                # Model concluded with final answer
                self._log("final_answer", content)
                self.conversation_history.append({"role": "user", "content": user_prompt})
                self.conversation_history.append({"role": "assistant", "content": content})
                return content

        fallback = "Reached maximum execution depth."
        self._log("final_answer", fallback)
        return fallback
