"""
Unit tests for JARVIS Long-Term Semantic Memory Engine (Phase 5).
Tests cover vector math, SQLite key-value CRUD, semantic chunk embedding,
fallback embedding generation, tool registry execution, and prompt injection.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.core import JarvisAgent
from agent.prompts import build_system_prompt
from memory.memory_store import (
    MemoryStore,
    cosine_similarity,
    generate_fallback_embedding,
    pack_embedding,
    unpack_embedding,
)
from tools.registry import registry


@pytest.fixture
def temp_store(tmp_path: Path) -> MemoryStore:
    """Provide an isolated MemoryStore with a fresh temporary SQLite database."""
    db_file = tmp_path / "test_memory.db"
    store = MemoryStore(db_path=str(db_file))
    yield store
    store.clear()


def test_cosine_similarity_math():
    """Verify cosine similarity calculation edge cases and accuracy."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0

    v_orth = [0.0, 1.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v_orth), 0.001) == 0.0

    v_opp = [-1.0, 0.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v_opp), 0.001) == -1.0

    # Mismatched lengths and empty vectors return 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_embedding_pack_and_unpack():
    """Verify float vector binary serialization round-trip."""
    original = [0.12345, -0.6789, 1.0, 0.0, 3.14159]
    blob = pack_embedding(original)
    assert isinstance(blob, bytes)
    assert len(blob) == len(original) * 4

    unpacked = unpack_embedding(blob)
    assert len(unpacked) == len(original)
    for orig, unp in zip(original, unpacked):
        assert pytest.approx(orig, 1e-5) == unp

    assert unpack_embedding(b"") == []


def test_fallback_embedding_generation():
    """Verify deterministic fallback vector generation and semantic correlation."""
    v1 = generate_fallback_embedding("User prefers Python and dark mode interface")
    v2 = generate_fallback_embedding("User likes dark mode UI and coding in Python")
    v_unrelated = generate_fallback_embedding("Quantum astrophysics cosmic inflation")

    assert len(v1) == 128
    assert len(v2) == 128

    sim_related = cosine_similarity(v1, v2)
    sim_unrelated = cosine_similarity(v1, v_unrelated)

    assert sim_related > 0.50
    assert sim_related > sim_unrelated


def test_ollama_embedding_generation_mocked(temp_store: MemoryStore):
    """Verify get_embedding uses Ollama response when 200, and falls back on failure."""
    # 1. Successful Ollama response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3, 0.4]}

    with patch("requests.post", return_value=mock_resp):
        emb = temp_store.get_embedding("test query")
        assert emb == [0.1, 0.2, 0.3, 0.4]

    # 2. Failed Ollama response falls back gracefully
    with patch("requests.post", side_effect=Exception("Connection refused")):
        fallback_emb = temp_store.get_embedding("test query")
        assert len(fallback_emb) == 128
        assert any(x != 0.0 for x in fallback_emb)


def test_key_values_crud(temp_store: MemoryStore):
    """Verify insert, retrieve, update, list, and delete in key_values."""
    # Insert
    temp_store.remember_key_value("owner_name", "Alice", category="personal")
    assert temp_store.get_key_value("owner_name") == "Alice"

    # Case insensitive key
    assert temp_store.get_key_value("OWNER_NAME") == "Alice"

    # Update on conflict
    temp_store.remember_key_value("owner_name", "Bob", category="personal")
    assert temp_store.get_key_value("owner_name") == "Bob"

    # List
    temp_store.remember_key_value("favorite_editor", "VS Code", category="tooling")
    kvs = temp_store.list_key_values()
    assert len(kvs) == 2

    kvs_filtered = temp_store.list_key_values(category="tooling")
    assert len(kvs_filtered) == 1
    assert kvs_filtered[0]["key"] == "favorite_editor"

    # Delete
    deleted = temp_store.delete_key_value("owner_name")
    assert deleted is True
    assert temp_store.get_key_value("owner_name") is None
    assert temp_store.delete_key_value("nonexistent") is False


def test_semantic_chunks_and_search(temp_store: MemoryStore):
    """Verify semantic chunk storage and vector similarity query ranking."""
    temp_store.remember_fact_chunk(
        "The deploy server IP is 192.168.1.100",
        metadata={"category": "infra"},
    )
    temp_store.remember_fact_chunk(
        "Project repository is located at github.com/user/project",
        metadata={"category": "code"},
    )

    results = temp_store.search_semantic("deploy server IP address", limit=2, threshold=0.30)
    assert len(results) > 0
    assert "192.168.1.100" in results[0]["content"]
    assert results[0]["metadata"]["category"] == "infra"


def test_remember_fact_and_recall_facts(temp_store: MemoryStore):
    """Verify unified remember_fact and recall_facts methods."""
    res = temp_store.remember_fact(
        "The primary database password is saved in vault",
        category="security",
        key="db_vault_status",
    )
    assert "Remembered fact" in res
    assert "db_vault_status" in res

    # Retrieve via key-value
    assert temp_store.get_key_value("db_vault_status") == "The primary database password is saved in vault"

    # Recall via query
    recalled = temp_store.recall_facts("database password vault")
    assert "database password is saved in vault" in recalled

    # Empty query recall
    empty_recalled = temp_store.recall_facts("completely unrelated extraterrestrial galaxy", threshold=0.99)
    assert "No relevant memories found" in empty_recalled


def test_get_relevant_context_formatting(temp_store: MemoryStore):
    """Verify get_relevant_context produces clean context lines for prompts."""
    temp_store.remember_key_value("username", "Administrator", category="auth")
    temp_store.remember_fact_chunk("Preferred shell is PowerShell 7")

    # Check key matching
    context = temp_store.get_relevant_context("What is the username of current session?")
    assert "username: Administrator" in context

    # Non-matching prompt returns empty string
    empty_context = temp_store.get_relevant_context("xyzabc unrelated 123", threshold=0.99)
    assert empty_context == ""


def test_memory_tools_registered_and_executable(temp_store: MemoryStore):
    """Verify remember_fact and recall_facts tools are in registry and execute properly."""
    tool_names = registry.list_tool_names()
    assert "remember_fact" in tool_names
    assert "recall_facts" in tool_names

    # Patch singleton memory_store in registry to use temp_store
    with patch("memory.memory_store.memory_store", temp_store):
        # Execute remember_fact tool
        out = registry.execute("remember_fact", {
            "fact": "Always use 4 spaces for Python indentation",
            "category": "coding",
            "key": "python_indent",
        })
        assert "Remembered fact" in out

        # Execute recall_facts tool
        recall_out = registry.execute("recall_facts", {
            "query": "Python indentation rule",
            "limit": 2,
        })
        assert "Always use 4 spaces" in recall_out


def test_build_system_prompt_with_memory():
    """Verify build_system_prompt appends [Remembered Context] when provided."""
    prompt_without = build_system_prompt(tool_descriptions="tool info", tool_names=["test_tool"])
    assert "[Remembered Context]" not in prompt_without

    prompt_with = build_system_prompt(
        tool_descriptions="tool info",
        tool_names=["test_tool"],
        memory_context="- User prefers dark mode\n- username: Alice",
    )
    assert "[Remembered Context]" in prompt_with
    assert "User prefers dark mode" in prompt_with
    assert "username: Alice" in prompt_with


def test_agent_injects_memory_context_into_react_loop(temp_store: MemoryStore):
    """Verify JarvisAgent ReAct loop injects retrieved memory into system prompt."""
    temp_store.remember_fact("The target test project is Jolly-Hawking", key="project_name")

    mock_llm = MagicMock()
    mock_llm.chat.return_value = {
        "content": "Thought: I know the project.\nFinal Answer: Project is Jolly-Hawking."
    }

    agent = JarvisAgent(llm_client=mock_llm, verbose=False)

    with patch("agent.core.memory_store", temp_store):
        final = agent.run("What is the project_name?")
        assert "Jolly-Hawking" in final

        # Check that the system message passed to LLM included the remembered context
        chat_call_args = mock_llm.chat.call_args[1]["messages"]
        system_msg = chat_call_args[0]["content"]
        assert "[Remembered Context]" in system_msg
        assert "project_name" in system_msg
