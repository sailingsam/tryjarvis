"""Embeddings — rented "meaning vectors", behind an interface.

Turns text into a vector so memory can be searched by meaning, not just
keywords ("what can I eat?" should find "User is vegetarian"). Default is a
small local model (fastembed / ONNX, CPU, no API key, no per-call cost, and
private). This is NOT the local-brain we rejected — it's a tiny utility, not
the reasoning model. Swap to a hosted embedder (Voyage/OpenAI) later without
touching memory or the brain.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class LocalEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]
