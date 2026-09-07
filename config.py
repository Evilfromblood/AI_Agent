"""
Configuration settings for the local JARVIS desktop assistant.
"""

import os
from typing import List, Optional
from pydantic import BaseModel, Field


class AssistantConfig(BaseModel):
    """Central configuration for JARVIS assistant."""

    # Ollama settings (Local Primary Brain)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Local Ollama API endpoint base URL",
    )
    target_model: str = Field(
        default="gemma4:latest",
        description="Primary target model for inference",
    )
    fallback_models: List[str] = Field(
        default_factory=lambda: ["gemma4:12b", "gemma3:4b", "gemma3:12b", "glm-4.7-flash:latest"],
        description="Priority order of fallback models if target model is not present",
    )

    # Online Supporting Brain (Cloud Co-Pilot: Gemini 2.5 Flash)
    online_provider: str = Field(
        default="gemini",
        description="Online co-pilot LLM provider ('gemini' or 'openai')",
    )
    gemini_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("ONLINE_API_KEY"),
        description="API key for Google Gemini",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Cloud Gemini model for complex reasoning and failure diagnostics",
    )
    enable_online_fallback: bool = Field(
        default=True,
        description="Enable automatic escalation to online co-pilot when local tool errors persist",
    )
    consecutive_failure_threshold: int = Field(
        default=2,
        description="Consecutive tool failures before escalating to online co-pilot",
    )

    # Execution limits
    command_timeout: int = Field(
        default=30,
        description="Timeout in seconds for terminal command executions",
    )
    max_chars_read: int = Field(
        default=5000,
        description="Maximum characters returned when reading a file",
    )
    max_react_steps: int = Field(
        default=10,
        description="Maximum iterative ReAct loop cycles before terminating",
    )

    # Browser automation settings
    headless_browser: bool = Field(
        default=True,
        description="Run browser in headless mode by default",
    )
    browser_page_load_timeout: int = Field(
        default=20,
        description="Browser page load timeout in seconds",
    )

    # Safety and guardrail settings
    destructive_keywords: List[str] = Field(
        default_factory=lambda: [
            "rm ",
            "rm -",
            "del ",
            "del /",
            "erase ",
            "format ",
            "rmdir ",
            "rd /",
            "shutdown ",
            "reboot ",
            "taskkill ",
            "pkill ",
            "kill -9",
            "mkfs",
            "dd if=",
            ":(){:|:&};:",
            "drop database",
            "drop table",
            "truncate ",
        ],
        description="Keywords indicating potentially destructive terminal commands",
    )


# Singleton default configuration
config = AssistantConfig()
