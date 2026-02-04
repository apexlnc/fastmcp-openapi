from __future__ import annotations

from typing import Any

try:  # Optional dependency
    import numpy as np
    from fastembed import TextEmbedding
except Exception:  # pragma: no cover - optional dependency
    np = None
    TextEmbedding = None


class SemanticIndex:
    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name
        self._model = None
        self._ids: list[str] = []
        self._matrix = None
        self._matrix_norm = None

    @property
    def available(self) -> bool:
        return TextEmbedding is not None and np is not None

    def clear(self) -> None:
        self._ids = []
        self._matrix = None
        self._matrix_norm = None

    def embed_texts(self, texts: list[str]) -> list[Any]:
        if not self.available:
            return []
        if TextEmbedding is None:
            return []
        model = self._model
        if model is None:
            if self._model_name:
                model = TextEmbedding(model_name=self._model_name)
            else:
                model = TextEmbedding()
            self._model = model
        embeddings = list(model.embed(texts))
        return embeddings

    def build(self, rows: list[tuple[str, Any]]) -> list[tuple[str, int, bytes]]:
        if not self.available:
            return []
        if np is None:
            return []
        if not rows:
            self.clear()
            return []

        ids = [row[0] for row in rows]
        texts = [row[1] for row in rows]
        vectors = [np.asarray(vec, dtype=np.float32) for vec in self.embed_texts(texts)]
        if not vectors:
            self.clear()
            return []

        matrix = np.vstack(vectors)
        self._ids = ids
        self._matrix = matrix
        self._matrix_norm = _normalize_matrix(matrix)

        payloads: list[tuple[str, int, bytes]] = []
        for endpoint_id, vec in zip(ids, vectors):
            payloads.append((endpoint_id, int(vec.size), vec.tobytes()))
        return payloads

    def load(self, rows: list[tuple[str, int, bytes]]) -> None:
        if not self.available:
            return
        if np is None:
            return
        if not rows:
            self.clear()
            return

        ids: list[str] = []
        vectors = []
        for endpoint_id, dim, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            if dim != vec.size:
                continue
            ids.append(endpoint_id)
            vectors.append(vec)

        if not vectors:
            self.clear()
            return

        matrix = np.vstack(vectors)
        self._ids = ids
        self._matrix = matrix
        self._matrix_norm = _normalize_matrix(matrix)

    def search(self, query: str, top_k: int = 25) -> list[str]:
        if not self.available or self._matrix_norm is None:
            return []
        if np is None:
            return []

        embeddings = self.embed_texts([query])
        if not embeddings:
            return []
        vector = np.asarray(embeddings[0], dtype=np.float32)
        vector = _normalize_vector(vector)
        scores = self._matrix_norm @ vector
        if scores.size == 0:
            return []
        k = min(top_k, scores.size)
        idx = np.argpartition(-scores, k - 1)[:k]
        scored = [(float(scores[i]), self._ids[i]) for i in idx]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[1] for item in scored]


def _normalize_vector(vector: Any) -> Any:
    if np is None:
        return vector
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _normalize_matrix(matrix: Any) -> Any:
    if np is None:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
