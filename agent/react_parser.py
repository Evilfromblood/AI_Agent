"""
Robust parser for JSON ReAct output format.
Extracts Thought, Action, Action Input (JSON), and Final Answer from LLM responses.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ReActStep:
    """Represents a parsed step from the ReAct cycle."""
    thought: str = ""
    action: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    final_answer: Optional[str] = None
    raw_output: str = ""
    is_final: bool = False
    parse_error: Optional[str] = None


class ReActParser:
    """Extracts and cleans ReAct structure from model responses."""

    @staticmethod
    def _clean_json_str(text: str) -> str:
        """Strip markdown fences and leading/trailing noise around JSON."""
        cleaned = text.strip()
        # Remove ```json ... ``` or ``` ... ```
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # If wrapped in quotes
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()

        return cleaned

    @staticmethod
    def _extract_balanced_json(text: str) -> Optional[str]:
        """Extract the first balanced JSON object {...} from text."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
        return None

    @classmethod
    def parse(cls, text: str) -> ReActStep:
        """
        Parse raw LLM response text into a ReActStep.
        """
        step = ReActStep(raw_output=text)

        # 1. Check for Final Answer
        final_answer_match = re.search(r"Final Answer\s*:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
        if final_answer_match and ("Action:" not in text or text.index("Final Answer") > text.index("Action:")):
            step.is_final = True
            step.final_answer = final_answer_match.group(1).strip()
            # Extract preceding thought if any
            thought_match = re.search(r"Thought\s*:\s*(.*?)(?=Final Answer|$)", text, re.DOTALL | re.IGNORECASE)
            if thought_match:
                step.thought = thought_match.group(1).strip()
            return step

        # 2. Extract Thought
        thought_match = re.search(r"Thought\s*:\s*(.*?)(?=Action\s*:|Final Answer\s*:|$)", text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            step.thought = thought_match.group(1).strip()

        # 3. Extract Action
        action_match = re.search(r"Action\s*:\s*([a-zA-Z0-9_\-\.]+)", text, re.IGNORECASE)
        if action_match:
            step.action = action_match.group(1).strip()

        # 4. Extract Action Input
        input_match = re.search(r"Action Input\s*:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
        if input_match:
            raw_input = input_match.group(1).strip()

            # Cut off hallucinated observation or channel tokens
            cutoff_patterns = [
                r"(?:<[^>]+>|\s)*Observation\s*:",
                r"\n\s*Thought\s*:",
                r"\n\s*Final Answer\s*:",
            ]
            for cp in cutoff_patterns:
                cp_match = re.search(cp, raw_input, re.IGNORECASE)
                if cp_match:
                    raw_input = raw_input[:cp_match.start()].strip()

            cleaned_input = cls._clean_json_str(raw_input)

            if not cleaned_input or cleaned_input.lower() in ("{}", "none", "null", "no arguments"):
                step.action_input = {}
            else:
                # First try direct json.loads
                try:
                    parsed_json = json.loads(cleaned_input)
                    if isinstance(parsed_json, dict):
                        step.action_input = parsed_json
                    else:
                        step.action_input = {"value": parsed_json}
                except json.JSONDecodeError:
                    # Try finding balanced JSON object {...}
                    balanced = cls._extract_balanced_json(cleaned_input)
                    if balanced:
                        try:
                            step.action_input = json.loads(balanced)
                        except Exception:
                            step.parse_error = f"Failed to parse JSON Action Input: '{cleaned_input}'"
                    else:
                        step.action_input = {"arg": cleaned_input}

        # If neither action nor final answer was found, treat entire text as final answer or raw output
        if not step.action and not step.final_answer:
            if step.thought:
                step.final_answer = step.thought
                step.is_final = True
            else:
                step.final_answer = text.strip()
                step.is_final = True

        return step
