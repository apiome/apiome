"""
Embedding service for data_snapshot vectorization.

Calls Ollama /api/embed to produce vectors for semantic/LLM search.
Uses the same model and dimensions as the UI (qwen3-embedding:4b, 2000 dims).
pgvector HNSW index max is 2000 dimensions.
Uses stdlib urllib (no extra dependency).
"""

import json
import logging
from typing import Optional, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "qwen3-embedding:4b"
EMBEDDING_DIMENSIONS = 2000  # pgvector HNSW max; must match data_snapshot.embedding vector(2000)


def get_embedding(text: str) -> Optional[List[float]]:
    """
    Get a single embedding vector for the given text from Ollama.

    Args:
        text: Input text (e.g. JSON string of record data)

    Returns:
        Embedding vector or None if Ollama is unavailable or errors
    """
    base_url = settings.ollama_base_url.rstrip("/")
    url = f"{base_url}/api/embed"
    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": text,
        "dimensions": EMBEDDING_DIMENSIONS,
        "truncate": True,
    }).encode("utf-8")
    req = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                logger.warning("[embedding] Ollama embed failed: %s %s", resp.status, resp.reason)
                return None
            data = json.loads(resp.read().decode())
    except (URLError, HTTPError, OSError) as e:
        logger.warning("[embedding] Ollama request error: %s", e)
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("[embedding] Parse error: %s", e)
        return None

    vectors = data.get("embeddings")
    if not vectors or not isinstance(vectors, list) or len(vectors) == 0:
        logger.warning("[embedding] Unexpected Ollama response shape")
        return None
    first = vectors[0]
    if not isinstance(first, list):
        return None
    return [float(x) for x in first]


def embed_record_data(data: dict) -> Optional[List[float]]:
    """
    Generate embedding for record data (JSON-serialized).

    Used by data record insert/update flows to persist embedding in data_snapshot.
    """
    text = json.dumps(data) if isinstance(data, dict) else "{}"
    return get_embedding(text)
