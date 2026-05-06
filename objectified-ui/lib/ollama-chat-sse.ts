/**
 * Accumulate assistant text from an Ollama-compatible SSE response (data: JSON lines).
 */

export async function accumulateOllamaSse(
  response: Response,
  signal: AbortSignal | undefined,
  onDelta?: (accumulated: string) => void,
): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return '';

  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';

  while (true) {
    if (signal?.aborted) {
      await reader.cancel().catch(() => {});
      break;
    }
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim() || !line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') continue;
      try {
        const event = JSON.parse(data) as { content?: string };
        if (event.content) {
          accumulated += event.content;
          onDelta?.(accumulated);
        }
      } catch {
        /* ignore */
      }
    }
  }

  return accumulated;
}
