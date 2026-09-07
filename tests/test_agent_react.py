"""
Unit tests for ReAct parsing, prompt composition, tool registry, and agent core.
"""

from unittest.mock import MagicMock
from agent.core import JarvisAgent
from agent.llm_client import LLMClient
from agent.prompts import build_system_prompt
from agent.react_parser import ReActParser
from tools.registry import ToolRegistry


def test_react_parser_action_step():
    text = """
    Thought: I need to inspect the current folder.
    Action: list_directory
    Action Input: {"path": "."}
    """
    step = ReActParser.parse(text)
    assert not step.is_final
    assert step.thought == "I need to inspect the current folder."
    assert step.action == "list_directory"
    assert step.action_input == {"path": "."}


def test_react_parser_fenced_json():
    text = """
    Thought: Writing a file.
    Action: write_file
    Action Input: ```json
    {
        "filepath": "output.txt",
        "content": "Hello World"
    }
    ```
    """
    step = ReActParser.parse(text)
    assert step.action == "write_file"
    assert step.action_input == {"filepath": "output.txt", "content": "Hello World"}


def test_react_parser_final_answer():
    text = """
    Thought: I have finished inspecting the directory and know all files.
    Final Answer: The directory contains main.py, config.py, and requirements.txt.
    """
    step = ReActParser.parse(text)
    assert step.is_final
    assert "main.py" in step.final_answer


def test_react_parser_inline_channel_token():
    text = 'Thought: Need to read file.\nAction: read_file\nAction Input: {"filepath": "requirements.txt", "max_chars": 500}<channel|>Observation: dummy'
    step = ReActParser.parse(text)
    assert not step.is_final
    assert step.action == "read_file"
    assert step.action_input == {"filepath": "requirements.txt", "max_chars": 500}


def test_tool_registry_registration_and_execution():
    custom_reg = ToolRegistry()

    @custom_reg.register
    def add_numbers(a: int, b: int = 10) -> int:
        """Add two numbers together."""
        return a + b

    assert "add_numbers" in custom_reg.list_tool_names()
    desc = custom_reg.get_react_descriptions()
    assert "add_numbers" in desc
    assert "Add two numbers" in desc

    # Valid execution
    res = custom_reg.execute("add_numbers", {"a": 5, "b": 15})
    assert res == "20"

    # Execution with default
    res2 = custom_reg.execute("add_numbers", {"a": 7})
    assert res2 == "17"

    # Invalid tool
    res_err = custom_reg.execute("non_existent", {})
    assert "not found" in res_err.lower()


def test_jarvis_agent_react_execution_flow():
    mock_llm = MagicMock(spec=LLMClient)
    # Simulate 2 steps:
    # 1. Ask for directory listing
    # 2. Conclude with final answer
    mock_llm.chat.side_effect = [
        {
            "role": "assistant",
            "content": "Thought: I must list files.\nAction: list_directory\nAction Input: {\"path\": \".\"}",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: I have the listing.\nFinal Answer: Directory listing complete.",
            "tool_calls": [],
        }
    ]

    agent = JarvisAgent(llm_client=mock_llm, mode="react", verbose=False)
    answer = agent.run("What files are here?")

    assert answer == "Directory listing complete."
    assert mock_llm.chat.call_count == 2
    assert len(agent.conversation_history) == 2


def test_llm_client_options_and_empty_fallback():
    client = LLMClient(model="test_model")
    client.client = MagicMock()

    # Mock empty response from ollama
    mock_msg = MagicMock()
    mock_msg.content = ""
    mock_msg.tool_calls = []
    mock_resp = MagicMock()
    mock_resp.message = mock_msg
    client.client.chat.return_value = mock_resp

    res = client.chat(messages=[{"role": "user", "content": "hi"}])
    # Verify num_ctx: 8192 was sent
    call_kwargs = client.client.chat.call_args.kwargs
    assert call_kwargs["options"]["num_ctx"] == 8192
    assert call_kwargs["options"]["temperature"] == 0.2

    # Verify empty response was caught and fallback returned
    assert "empty response" in res["content"].lower()
