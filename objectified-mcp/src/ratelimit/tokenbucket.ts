/**
 * Redis-backed token bucket (MCP-1.5). Bootstrap implementation is a no-op allow.
 */
export class TokenBucketLimiter {
  async take(_key: string): Promise<boolean> {
    void _key;
    return true;
  }
}
