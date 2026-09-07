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


def test_react_parser_plan_and_critique():
    text = """
    Thought: Need to analyze system load.
    Plan: 1. Get system metrics. 2. Compare against threshold.
    Critique: Previous scraper attempt timed out, pivoting to system tools.
    Action: get_system_stats
    Action Input: {}
    """
    step = ReActParser.parse(text)
    assert not step.is_final
    assert step.thought == "Need to analyze system load."
    assert "1. Get system metrics" in step.plan
    assert "Previous scraper attempt timed out" in step.critique
    assert step.action == "get_system_stats"
    assert step.action_input == {}


def test_react_parser_token_stripping():
    text = "<start_of_turn>Thought: Checking files.<channel|>Plan: List current folder.<end_of_turn>Action: list_directory\nAction Input: {}\n<|im_end|>"
    step = ReActParser.parse(text)
    assert "<start_of_turn>" not in step.raw_output
    assert "<channel|>" not in step.raw_output
    assert "<end_of_turn>" not in step.raw_output
    assert step.action == "list_directory"


def test_gemini_wrapper_chat_mocked():
    from agent.llm_client import GeminiClientWrapper

    wrapper = GeminiClientWrapper(api_key="mock_key", model="gemini-3.6-flash")
    assert wrapper.model == "gemini-3.6-flash"
    mock_genai_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Gemini Co-Pilot Response"
    mock_genai_client.models.generate_content.return_value = mock_resp
    wrapper._client = mock_genai_client

    result = wrapper.chat([{"role": "user", "content": "Explain quantum entanglement"}])
    assert result["role"] == "assistant"
    assert result["content"] == "Gemini Co-Pilot Response"
    mock_genai_client.models.generate_content.assert_called_once()

    # Also verify default initialization picks up config.gemini_model
    default_wrapper = GeminiClientWrapper(api_key="mock_key")
    assert default_wrapper.model == "gemini-3.6-flash"


def test_jarvis_agent_failure_escalation_to_gemini():
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.gemini = MagicMock()
    mock_llm.gemini.is_available = True

    # Simulate:
    # Turn 1: Try read_file -> Error
    # Turn 2: Try read_file -> Error (triggers failure escalation to chat_online)
    # Turn 3: Conclude with final answer
    mock_llm.chat.side_effect = [
        {
            "role": "assistant",
            "content": "Thought: Reading file.\nAction: read_file\nAction Input: {\"filepath\": \"non_existent_file.xyz\"}",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: Retrying read.\nAction: read_file\nAction Input: {\"filepath\": \"non_existent_file.xyz\"}",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: Moving on.\nFinal Answer: Task aborted safely.",
            "tool_calls": [],
        },
    ]

    mock_llm.chat_online.return_value = {
        "role": "assistant",
        "content": "File does not exist. Suggest using search_files or list_directory first.",
        "tool_calls": [],
    }

    agent = JarvisAgent(llm_client=mock_llm, mode="react", verbose=False)
    final_ans = agent.run("Find my notes")

    assert final_ans == "Task aborted safely."
    # chat_online should have been invoked for escalation
    mock_llm.chat_online.assert_called_once()


def test_react_prompt_critical_rule_present():
    prompt = build_system_prompt("tool descriptions here", ["tool1", "tool2"])
    expected_rule = (
        "CRITICAL: If the user request requires interacting with the system "
        "(getting stats, launching apps, typing, clicking, reading/writing files), "
        "you MUST output an `Action:` block first. You are STRICTLY FORBIDDEN from "
        "reporting results or stating an action was performed unless you have "
        "received the corresponding tool `Observation:` in the loop."
    )
    assert expected_rule in prompt


def test_tool_execution_bypass_interception_final_answer():
    mock_llm = MagicMock(spec=LLMClient)
    # Turn 1: Premature Final Answer without tool execution (hallucinating stats)
    # Turn 2: Follows system reminder and outputs Action
    # Turn 3: Returns Final Answer with verified data
    mock_llm.chat.side_effect = [
        {
            "role": "assistant",
            "content": "Thought: I will provide the CPU stats.\nFinal Answer: CPU is 12% and memory is 45%.",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: I need to call get_system_stats.\nAction: get_system_stats\nAction Input: {}",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: Observation received.\nFinal Answer: Verified CPU is 8.2%.",
            "tool_calls": [],
        },
    ]

    agent = JarvisAgent(llm_client=mock_llm, mode="react", verbose=False)
    final_ans = agent.run("Get my system stats")

    assert final_ans == "Verified CPU is 8.2%."
    assert mock_llm.chat.call_count == 3
    # Check that the second call received the interception reminder
    second_call_messages = mock_llm.chat.call_args_list[1].kwargs["messages"]
    reminder_present = any(
        "You answered without executing required tools. Output an Action block to execute the first step."
        in m.get("content", "")
        for m in second_call_messages
    )
    assert reminder_present


def test_tool_execution_bypass_interception_direct_response():
    mock_llm = MagicMock(spec=LLMClient)
    # Turn 1: Raw text without Action or Final Answer prefix
    # Turn 2: Follows system reminder and outputs Action
    # Turn 3: Final Answer
    mock_llm.chat.side_effect = [
        {
            "role": "assistant",
            "content": "I launched Notepad and typed hello for you.",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Thought: Executing tool.\nAction: launch_application\nAction Input: {\"app_name\": \"notepad\"}",
            "tool_calls": [],
        },
        {
            "role": "assistant",
            "content": "Final Answer: Notepad launched successfully.",
            "tool_calls": [],
        },
    ]

    agent = JarvisAgent(llm_client=mock_llm, mode="react", verbose=False)
    final_ans = agent.run("Open notepad and write hello")

    assert final_ans == "Notepad launched successfully."
    assert mock_llm.chat.call_count == 3


def test_non_tool_prompt_not_intercepted():
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = {
        "role": "assistant",
        "content": "Final Answer: Paris is the capital of France.",
        "tool_calls": [],
    }

    agent = JarvisAgent(llm_client=mock_llm, mode="react", verbose=False)
    final_ans = agent.run("What is the capital of France?")

    assert final_ans == "Paris is the capital of France."
    assert mock_llm.chat.call_count == 1

