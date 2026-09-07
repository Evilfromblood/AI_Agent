"""
LLM Client for local Ollama and vLLM inference.
Handles model discovery, automatic fallbacks, and chat completions.
"""

from typing import Any, Dict, List, Optional
import ollama
import requests

from config import config


class LLMClient:
    """Client for local Ollama inference."""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None):
        self.host = host or config.ollama_base_url
        self.client = ollama.Client(host=self.host)
        self.selected_model = model
        self.available_models: List[str] = []

    def check_connection(self) -> bool:
        """Verify if Ollama instance is reachable."""
        try:
            resp = requests.get(f"{self.host.rstrip('/')}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Fetch list of available model names from local Ollama."""
        try:
            res = self.client.list()
            # ollama-python returns models as a list of Model objects or dicts
            models = []
            model_items = res.get("models", []) if isinstance(res, dict) else getattr(res, "models", [])
            for item in model_items:
                name = item.get("name") if isinstance(item, dict) else getattr(item, "model", None) or getattr(item, "name", None)
                if name:
                    models.append(name)
            self.available_models = models
            return models
        except Exception as e:
            # Fallback to direct HTTP request
            try:
                resp = requests.get(f"{self.host.rstrip('/')}/api/tags", timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", []) if "name" in m]
                    self.available_models = models
                    return models
            except Exception:
                pass
            return []

    def resolve_model(self) -> str:
        """
        Determine which model to use, prioritizing target_model, then fallback_models.
        """
        if self.selected_model:
            return self.selected_model

        available = self.list_models()
        if not available:
            # If Ollama is not answering, default to configured target model
            self.selected_model = config.target_model
            return self.selected_model

        # 1. Try target model
        if config.target_model in available:
            self.selected_model = config.target_model
            return self.selected_model

        # Check tag-agnostic match (e.g. 'gemma4' matches 'gemma4:latest')
        for model_name in available:
            if model_name.startswith(config.target_model.split(":")[0]):
                self.selected_model = model_name
                return self.selected_model

        # 2. Try fallbacks
        for fb in config.fallback_models:
            if fb in available:
                self.selected_model = fb
                return self.selected_model
            for model_name in available:
                if model_name.startswith(fb.split(":")[0]):
                    self.selected_model = model_name
                    return self.selected_model

        # 3. Default to first available model
        self.selected_model = available[0]
        return self.selected_model

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Send chat completion request to local Ollama.
        :param messages: List of chat messages [{"role": "...", "content": "..."}]
        :param tools: Optional list of tool definitions for native tool calling
        :param model: Optional override model
        :param temperature: Generation temperature
        :return: Response dictionary containing 'message' and 'tool_calls'
        """
        active_model = model or self.resolve_model()
        payload = {
            "model": active_model,
            "messages": messages,
            "options": {
                "num_ctx": 8192,
                "temperature": temperature,
            },
        }
        if tools:
            payload["tools"] = tools

        empty_fallback = "[Model returned an empty response. Please retry or rephrase your prompt.]"

        try:
            response = self.client.chat(**payload)
            # Normalize response dict
            if hasattr(response, "message"):
                msg = response.message
                tool_calls = getattr(msg, "tool_calls", None) or []
                # Ensure tool_calls are dicts
                normalized_calls = []
                for tc in tool_calls:
                    if hasattr(tc, "function"):
                        normalized_calls.append({
                            "function": {
                                "name": getattr(tc.function, "name", ""),
                                "arguments": getattr(tc.function, "arguments", {}),
                            }
                        })
                    elif isinstance(tc, dict):
                        normalized_calls.append(tc)

                raw_content = getattr(msg, "content", "") or ""
                final_content = raw_content if (raw_content.strip() or normalized_calls) else empty_fallback

                return {
                    "role": "assistant",
                    "content": final_content,
                    "tool_calls": normalized_calls,
                }
            elif isinstance(response, dict):
                msg = response.get("message", {})
                tool_calls = msg.get("tool_calls", []) or []
                raw_content = msg.get("content", "") or ""
                final_content = raw_content if (raw_content.strip() or tool_calls) else empty_fallback
                return {
                    "role": "assistant",
                    "content": final_content,
                    "tool_calls": tool_calls,
                }
            else:
                raw_content = str(response).strip()
                return {
                    "role": "assistant",
                    "content": raw_content or empty_fallback,
                    "tool_calls": [],
                }
        except Exception as e:
            return {
                "role": "assistant",
                "content": f"[Error connecting to Ollama at {self.host} with model {active_model}: {str(e)}]",
                "tool_calls": [],
            }
