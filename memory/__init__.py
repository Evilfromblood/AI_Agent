"""
Memory package for JARVIS desktop assistant.
Exposes long-term semantic memory store with Ollama vector embeddings.
"""

from memory.memory_store import MemoryStore, memory_store

__all__ = [
    "MemoryStore",
    "memory_store",
]
