/**
 * API route to fetch available Ollama models
 * Filters out embedding/vectorization models to only show generative models
 */

import { NextResponse } from 'next/server';

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || 'http://localhost:11434';

/**
 * List of patterns that indicate a model is for embedding/vectorization
 * These models are not suitable for text generation
 */
const EMBEDDING_MODEL_PATTERNS = [
  'embed',           // nomic-embed-text, mxbai-embed-large, etc.
  'minilm',          // all-minilm
  'bge-',            // bge-small, bge-base, bge-large
  'e5-',             // e5-small, e5-base, e5-large
  'gte-',            // gte-small, gte-base, gte-large
  'arctic-embed',    // snowflake-arctic-embed
  'paraphrase',      // paraphrase-multilingual
  'sentence-',       // sentence-transformers based models
  'text2vec',        // text2vec models
  'instructor',      // instructor embeddings
];

/**
 * Check if a model name indicates it's an embedding model
 */
function isEmbeddingModel(modelName: string): boolean {
  const lowerName = modelName.toLowerCase();
  return EMBEDDING_MODEL_PATTERNS.some(pattern => lowerName.includes(pattern));
}

export async function GET() {
  try {
    const response = await fetch(`${OLLAMA_BASE_URL}/api/tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Ollama API error: ${response.statusText}`);
    }

    const data = await response.json();
    const allModels = data.models || [];

    // Filter out embedding/vectorization models
    const generativeModels = allModels.filter((model: { name: string }) =>
      !isEmbeddingModel(model.name)
    );

    return NextResponse.json({ success: true, models: generativeModels });
  } catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : 'Failed to fetch models';
    console.error('Error fetching Ollama models:', error);
    return NextResponse.json(
      { success: false, error: errorMessage },
      { status: 500 }
    );
  }
}

