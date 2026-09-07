"""
Long-Term Semantic Memory Engine for JARVIS desktop assistant.
Combines persistent SQLite storage, Ollama neural vector embeddings,
and deterministic fallback embeddings for recall and context injection.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import config
from tools.registry import register_tool


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def pack_embedding(vec: List[float]) -> bytes:
    """Pack list of floats into binary BLOB."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> List[float]:
    """Unpack binary BLOB into list of floats."""
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


STOP_WORDS = {
    "the", "a", "an", "is", "in", "it", "to", "of", "and", "or",
    "for", "on", "at", "by", "with", "from", "as", "this", "that",
    "are", "was", "were", "be", "been", "being",
}


def generate_fallback_embedding(text: str, dim: int = 128) -> List[float]:
    """
    Generate a deterministic, unit-normalized float vector from text tokens and n-grams.
    Filters common stop words and incorporates word prefixes and n-grams for semantic signal.
    """
    vec = [0.0] * dim
    clean = text.lower().strip()
    all_words = re.findall(r"\w+", clean)
    words = [w for w in all_words if w not in STOP_WORDS] or all_words
    if not words:
        return vec

    for i, word in enumerate(words):
        # Unigram hash
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 3.0

        # Subword / prefix hash
        if len(word) > 3:
            ph = int(hashlib.md5(word[:4].encode("utf-8")).hexdigest(), 16)
            vec[ph % dim] += 1.5

        # Bigram hash for contextual proximity
        if i > 0:
            bigram = f"{words[i - 1]}_{word}"
            bh = int(hashlib.sha256(bigram.encode("utf-8")).hexdigest(), 16)
            vec[bh % dim] += 2.0

    # Normalize to unit vector so dot product equals cosine similarity
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec



class MemoryStore:
    """
    Persistent SQLite Long-Term Memory Store for JARVIS.
    Supports structured key-value attributes and dense vector semantic chunks.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        """
        Initialize MemoryStore.
        :param db_path: Path to SQLite database file
        :param embedding_model: Target Ollama embedding model name
        """
        self.db_path = db_path or getattr(config, "memory_db_path", "jarvis_memory.db")
        self.embedding_model = embedding_model or getattr(config, "embedding_model", "nomic-embed-text")
        self._lock = threading.Lock()
        self._ollama_available: Optional[bool] = None
        self._last_ollama_check: float = 0.0
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with Row factory enabled."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite tables for key-values and semantic chunks."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS key_values (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_key_values_cat ON key_values (category);"
            )
            conn.commit()

    def get_embedding(self, text: str) -> List[float]:
        """
        Fetch dense float embedding from local Ollama embedding endpoint.
        Gracefully falls back to deterministic vector generator if Ollama is unreachable.
        """
        text = text.strip()
        if not text:
            return [0.0] * 128

        now = time.time()
        # Fast exit if Ollama was recently verified unreachable
        if self._ollama_available is False and (now - self._last_ollama_check) < 30.0:
            return generate_fallback_embedding(text)

        try:
            url = f"{config.ollama_base_url}/api/embeddings"
            payload = {
                "model": self.embedding_model,
                "prompt": text,
            }
            resp = requests.post(url, json=payload, timeout=0.5)
            if resp.status_code == 200:
                self._ollama_available = True
                data = resp.json()
                emb = data.get("embedding")
                if emb and isinstance(emb, list) and len(emb) > 0:
                    return [float(x) for x in emb]
            else:
                self._ollama_available = False
                self._last_ollama_check = now
        except Exception:
            self._ollama_available = False
            self._last_ollama_check = now

        return generate_fallback_embedding(text)

    def remember_key_value(
        self,
        key: str,
        value: str,
        category: str = "general",
    ) -> None:
        """Store or update a structured key-value attribute."""
        clean_key = key.strip().lower()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO key_values (key, value, category, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (clean_key, value.strip(), category.strip()),
            )
            conn.commit()

    def get_key_value(self, key: str) -> Optional[str]:
        """Retrieve a stored attribute by key."""
        clean_key = key.strip().lower()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM key_values WHERE key = ?;", (clean_key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def delete_key_value(self, key: str) -> bool:
        """Delete an attribute by key. Returns True if deleted."""
        clean_key = key.strip().lower()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM key_values WHERE key = ?;", (clean_key,))
            conn.commit()
            return cursor.rowcount > 0

    def list_key_values(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all stored key-value attributes, optionally filtered by category."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT key, value, category, updated_at FROM key_values WHERE category = ? ORDER BY key;",
                    (category.strip(),),
                )
            else:
                cursor.execute(
                    "SELECT key, value, category, updated_at FROM key_values ORDER BY key;"
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def remember_fact_chunk(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Embed and persist an unstructured fact chunk into semantic vector storage.
        :return: Inserted chunk row ID
        """
        content_clean = content.strip()
        meta = metadata or {}
        embedding = self.get_embedding(content_clean)
        blob = pack_embedding(embedding)
        meta_json = json.dumps(meta)

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO semantic_chunks (content, embedding, metadata, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP);
                """,
                (content_clean, blob, meta_json),
            )
            conn.commit()
            return cursor.lastrowid

    def search_semantic(
        self,
        query: str,
        limit: int = 3,
        threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform vector cosine similarity search against stored semantic chunks.
        :param query: Query string to match against
        :param limit: Maximum results to return
        :param threshold: Minimum similarity threshold (defaults to config)
        """
        min_sim = threshold if threshold is not None else getattr(config, "memory_similarity_threshold", 0.35)
        query_emb = self.get_embedding(query)

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, content, embedding, metadata, created_at FROM semantic_chunks;")
            rows = cursor.fetchall()

        results = []
        for row in rows:
            chunk_emb = unpack_embedding(row["embedding"])
            sim = cosine_similarity(query_emb, chunk_emb)
            if sim >= min_sim:
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "similarity": round(sim, 4),
                    "metadata": json.loads(row["metadata"] or "{}"),
                    "created_at": row["created_at"],
                })

        # Sort descending by cosine similarity
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def remember_fact(
        self,
        fact: str,
        category: str = "general",
        key: Optional[str] = None,
    ) -> str:
        """
        Unified API: Store fact into semantic memory and optional key-value table.
        """
        fact_clean = fact.strip()
        if not fact_clean:
            return "Error: Fact content cannot be empty."

        # Always store as semantic chunk
        meta = {"category": category}
        if key:
            meta["key"] = key
            self.remember_key_value(key=key, value=fact_clean, category=category)

        chunk_id = self.remember_fact_chunk(fact_clean, metadata=meta)

        if key:
            return f"Remembered fact #{chunk_id} under key '{key}' ({category}): {fact_clean}"
        return f"Remembered fact #{chunk_id} in category '{category}': {fact_clean}"

    def recall_facts(
        self,
        query: str,
        limit: int = 3,
        threshold: Optional[float] = None,
    ) -> str:
        """
        Search memory for facts matching the query.
        Returns a formatted markdown summary.
        """
        matches = self.search_semantic(query, limit=limit, threshold=threshold)

        # Also inspect key_values for keyword matches
        kv_matches = []
        query_lower = query.lower()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value, category FROM key_values;")
            for row in cursor.fetchall():
                if row["key"] in query_lower or query_lower in row["key"] or row["category"].lower() in query_lower:
                    kv_matches.append(f"- **{row['key']}** ({row['category']}): {row['value']}")

        if not matches and not kv_matches:
            return f"No relevant memories found for query: '{query}'."

        lines = [f"### Recalled Memories for '{query}':"]
        for m in matches:
            cat = m["metadata"].get("category", "general")
            lines.append(f"- (similarity: {m['similarity']:.2f}, {cat}) {m['content']}")

        if kv_matches:
            lines.append("\n**Matched Attributes:**")
            lines.extend(kv_matches[:limit])

        return "\n".join(lines)

    def get_relevant_context(
        self,
        prompt: str,
        threshold: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> str:
        """
        Retrieve formatted context lines from memory to inject into the system prompt.
        Returns an empty string if no relevant memories are found.
        """
        th = threshold if threshold is not None else getattr(config, "memory_similarity_threshold", 0.35)
        lim = limit if limit is not None else getattr(config, "memory_top_k", 3)

        matches = self.search_semantic(prompt, limit=lim, threshold=th)

        # Check key_values for keywords appearing directly in user prompt
        prompt_words = set(re.findall(r"\w+", prompt.lower()))
        kv_items = []
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM key_values;")
            for row in cursor.fetchall():
                if row["key"].lower() in prompt_words:
                    kv_items.append(f"- {row['key']}: {row['value']}")

        context_lines = []
        for m in matches:
            context_lines.append(f"- {m['content']}")
        for k in kv_items:
            if k not in context_lines:
                context_lines.append(k)

        if not context_lines:
            return ""

        return "\n".join(context_lines[:lim])

    def clear(self) -> None:
        """Clear all stored memories and key-value records."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM key_values;")
            cursor.execute("DELETE FROM semantic_chunks;")
            conn.commit()


# Default singleton instance
memory_store = MemoryStore()


# --- Tool Registrations for Agent ReAct & Native Tool Calling ---

@register_tool("remember_fact")
def tool_remember_fact(
    fact: str,
    category: str = "general",
    key: Optional[str] = None,
) -> str:
    """
    Persist an important fact, user preference, entity detail, or system instruction into long-term memory.
    :param fact: The fact or information to store permanently
    :param category: Optional topic category (e.g. 'preference', 'project', 'system', 'personal')
    :param key: Optional unique key if storing an explicit key-value attribute (e.g. 'user_name')
    """
    return memory_store.remember_fact(fact=fact, category=category, key=key)


@register_tool("recall_facts")
def tool_recall_facts(query: str, limit: int = 3) -> str:
    """
    Search long-term semantic memory and recall relevant facts, preferences, or entity details.
    :param query: Natural language search prompt or keywords to query against memory
    :param limit: Maximum number of relevant memories to retrieve
    """
    return memory_store.recall_facts(query=query, limit=limit)
