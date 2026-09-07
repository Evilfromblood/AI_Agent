"""
LLM Client for local Ollama and vLLM inference.
Handles model discovery, automatic fallbacks, and chat completions.
"""

from typing import Any, Dict, List, Optional
import ollama
import requests

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from config import config


class GeminiClientWrapper:
    """Wrapper for Google Gemini 3.6 Flash via official google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or config.gemini_api_key
        self.model = model or config.gemini_model
        self._client = None

    @property
    def client(self):
        if self._client is None and HAS_GENAI:
            key = self.api_key or config.gemini_api_key
            if key:
                try:
                    self._client = genai.Client(api_key=key)
                except Exception:
                    self._client = None
        return self._client

    @property
    def is_available(self) -> bool:
        return HAS_GENAI and bool(self.api_key or config.gemini_api_key)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """Send chat request to Gemini co-pilot."""
        if not HAS_GENAI:
            return {
                "role": "assistant",
                "content": "[google-genai package is not installed. Install with `pip install google-genai`.]",
                "tool_calls": [],
            }

        client = self.client
        if not client:
            return {
                "role": "assistant",
                "content": "[Gemini API key not configured. Please set GEMINI_API_KEY environment variable to enable cloud co-pilot.]",
                "tool_calls": [],
            }

        try:
            system_instruction = None
            conversation_parts = []

            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "system":
                    system_instruction = content
                elif role == "user":
                    conversation_parts.append(f"User: {content}")
                elif role == "assistant":
                    conversation_parts.append(f"Assistant: {content}")
                elif role == "tool":
                    conversation_parts.append(f"Observation ({msg.get('name', 'tool')}): {content}")

            prompt_text = "\n\n".join(conversation_parts)

            config_kwargs = {"temperature": temperature}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction

            resp = client.models.generate_content(
                model=self.model,
                contents=prompt_text,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            text_out = resp.text or ""
            return {
                "role": "assistant",
                "content": text_out.strip(),
                "tool_calls": [],
            }
        except Exception as e:
            return {
                "role": "assistant",
                "content": f"[Gemini Online Brain Error: {str(e)}]",
                "tool_calls": [],
            }


class LLMClient:
    """Client for local Ollama inference with optional cloud Gemini co-pilot."""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None, gemini_key: Optional[str] = None):
        self.host = host or config.ollama_base_url
        self.client = ollama.Client(host=self.host)
        self.selected_model = model
        self.available_models: List[str] = []
        self.gemini = GeminiClientWrapper(api_key=gemini_key)

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

    def chat_online(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """Send chat request directly to the online Gemini co-pilot."""
        return self.gemini.chat(messages, temperature=temperature)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        use_online: bool = False,
    ) -> Dict[str, Any]:
        """
        Send chat completion request to local Ollama (or cloud Gemini if use_online=True).
        :param messages: List of chat messages [{"role": "...", "content": "..."}]
        :param tools: Optional list of tool definitions for native tool calling
        :param model: Optional override model
        :param temperature: Generation temperature
        :param use_online: Whether to force routing to online Gemini co-pilot
        :return: Response dictionary containing 'message' and 'tool_calls'
        """
        if use_online:
            return self.chat_online(messages, temperature=temperature)

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
            # Fallback to online brain if enabled and available
            if config.enable_online_fallback and self.gemini.is_available:
                return self.chat_online(messages, temperature=temperature)

            return {
                "role": "assistant",
                "content": f"[Error connecting to Ollama at {self.host} with model {active_model}: {str(e)}]",
                "tool_calls": [],
            }
