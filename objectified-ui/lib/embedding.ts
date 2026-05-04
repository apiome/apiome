/**
 * Fetch embedding vector from Ollama for use with data_snapshot vectorization.
 * Uses OLLAMA_BASE_URL and qwen3-embedding:4b; dimensions limited to 2000 for pgvector HNSW index.
 */

const EMBEDDING_MODEL = 'qwen3-embedding:4b';
const EMBEDDING_DIMENSIONS = 2000; // pgvector HNSW index max

export interface EmbeddingOptions {
  dimensions?: number;
  signal?: AbortSignal;
}

/**
 * Get a single embedding vector for the given text from Ollama.
 * @param text - Input text (e.g. JSON.stringify(record.data))
 * @param options - Optional dimensions (default 2000 for index compatibility)
 * @returns Embedding vector or null if Ollama is unavailable or errors
 */
export async function getEmbedding(
  text: string,
  options: EmbeddingOptions = {}
): Promise<number[] | null> {
  const baseUrl = process.env.OLLAMA_BASE_URL || 'http://localhost:11434';
  const dimensions = options.dimensions ?? EMBEDDING_DIMENSIONS;
  const { signal } = options;

  try {
    const res = await fetch(`${baseUrl}/api/embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: EMBEDDING_MODEL,
        input: text,
        dimensions,
        truncate: true,
      }),
      signal,
    });

    if (!res.ok) {
      console.error(`[embedding] Ollama embed failed: ${res.status} ${res.statusText}`);
      return null;
    }

    const data = (await res.json()) as { embeddings?: number[][] };
    const vectors = data.embeddings;
    if (!Array.isArray(vectors) || vectors.length === 0 || !Array.isArray(vectors[0])) {
      console.error('[embedding] Unexpected Ollama response shape');
      return null;
    }

    return vectors[0];
  } catch (err) {
    console.error('[embedding] Ollama request error:', err);
    return null;
  }
}

export { EMBEDDING_MODEL, EMBEDDING_DIMENSIONS };

/**
 * Generate embedding for record data and return the vector (or null).
 * Used by snapshot insert/update flows to persist embedding via updateDataSnapshotEmbedding.
 */
export async function embedRecordData(data: Record<string, unknown>): Promise<number[] | null> {
  const text = typeof data === 'object' && data !== null ? JSON.stringify(data) : '{}';
  return getEmbedding(text);
}
