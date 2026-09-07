"""
Tool registry for JARVIS desktop assistant.
Provides registration decorator, schema generation for Ollama tool calling,
ReAct prompt documentation, and safe execution dispatching.
"""

import inspect
import json
from typing import Any, Callable, Dict, List, Optional, get_type_hints


class ToolRegistry:
    """Central registry of executable assistant tools."""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def register(self, func: Optional[Callable] = None, *, name: Optional[str] = None, description: Optional[str] = None):
        """
        Decorator to register a tool function.
        Can be used as @registry.register or @registry.register(name="custom_name")
        """
        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            tool_doc = description or (inspect.getdoc(fn) or "No description provided.")

            # Extract parameter schemas
            sig = inspect.signature(fn)
            type_hints = get_type_hints(fn)
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue

                param_type = type_hints.get(param_name, str)
                json_type = "string"
                if param_type in (int, float):
                    json_type = "number" if param_type is float else "integer"
                elif param_type is bool:
                    json_type = "boolean"
                elif param_type in (list, List):
                    json_type = "array"
                elif param_type in (dict, Dict):
                    json_type = "object"

                param_info: Dict[str, Any] = {"type": json_type}
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)
                else:
                    param_info["default"] = param.default

                properties[param_name] = param_info

            self._tools[tool_name] = fn
            self._metadata[tool_name] = {
                "name": tool_name,
                "description": tool_doc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            return fn

        if func is None:
            return decorator
        return decorator(func)

    def get_tool(self, name: str) -> Optional[Callable]:
        """Retrieve tool function by name."""
        return self._tools.get(name)

    def list_tool_names(self) -> List[str]:
        """List registered tool names."""
        return list(self._tools.keys())

    def get_ollama_tools(self) -> List[Dict[str, Any]]:
        """
        Return tool definitions compatible with Ollama's native tool calling API.
        """
        tools = []
        for name, meta in self._metadata.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": meta["name"],
                    "description": meta["description"],
                    "parameters": meta["parameters"],
                }
            })
        return tools

    def get_react_descriptions(self) -> str:
        """
        Return formatted tool descriptions suitable for JSON ReAct system prompts.
        """
        lines = []
        for name, meta in self._metadata.items():
            props = meta["parameters"]["properties"]
            reqs = meta["parameters"].get("required", [])
            args_desc = []
            for p_name, p_info in props.items():
                req_flag = "required" if p_name in reqs else f"optional, default: {p_info.get('default')}"
                args_desc.append(f"{p_name} ({p_info['type']}, {req_flag})")
            args_str = ", ".join(args_desc) if args_desc else "no parameters"
            lines.append(f"- {name}({args_str}): {meta['description']}")
        return "\n".join(lines)

    def execute(self, name: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """
        Safely execute registered tool by name with kwargs and return string output.
        """
        if name not in self._tools:
            return f"Error: Tool '{name}' not found. Available tools: {', '.join(self.list_tool_names())}"

        fn = self._tools[name]
        kwargs = kwargs or {}

        try:
            result = fn(**kwargs)
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2)
            return str(result)
        except TypeError as te:
            return f"Error executing tool '{name}': Invalid arguments provided ({te}). Required schema: {json.dumps(self._metadata[name]['parameters'])}"
        except PermissionError as pe:
            return f"Security Guardrail Interception: {pe}"
        except Exception as e:
            return f"Error executing tool '{name}': {type(e).__name__} - {str(e)}"


# Global registry singleton
registry = ToolRegistry()
