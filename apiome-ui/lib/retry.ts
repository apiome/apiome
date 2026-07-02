/**
 * Error recovery: retry failed operations with exponential backoff.
 * Used by import flow and other operations that may fail transiently.
 */

export interface RetryOptions {
  /** Maximum number of attempts (first try + retries). Default 3. */
  maxAttempts?: number;
  /** Initial delay in ms before first retry. Default 500. */
  initialDelayMs?: number;
  /** Maximum delay cap in ms. Default 10000. */
  maxDelayMs?: number;
  /** If provided, only retry when this returns true (e.g. transient errors). */
  isRetryable?: (error: unknown) => boolean;
  /** Optional label for logging. */
  label?: string;
}

const defaultOptions: Required<Omit<RetryOptions, 'isRetryable'>> & Pick<RetryOptions, 'isRetryable'> = {
  maxAttempts: 3,
  initialDelayMs: 500,
  maxDelayMs: 10000,
  label: 'operation',
  isRetryable: undefined
};

/** Returns true for errors that are typically transient (connection, timeout, 5xx). */
export function isTransientError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const msg = (error as Error).message?.toLowerCase() ?? String(error).toLowerCase();
  if (msg.includes('econnrefused') || msg.includes('econnreset') || msg.includes('etimedout')) return true;
  if (msg.includes('connection') || msg.includes('timeout') || msg.includes('network')) return true;
  if (msg.includes('deadlock') || msg.includes('serialization') || msg.includes('could not obtain')) return true;
  return false;
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Runs an async operation and retries on failure with exponential backoff.
 * @param fn Async function to run (no args).
 * @param options Retry options.
 * @returns Result of fn().
 * @throws Last error if all attempts fail.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> {
  const opts = { ...defaultOptions, ...options };
  const isRetryable = options.isRetryable ?? isTransientError;
  let lastError: unknown;
  let delayMs = opts.initialDelayMs;

  for (let attempt = 1; attempt <= opts.maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt === opts.maxAttempts) break;
      if (!isRetryable(err)) throw err;
      const capped = Math.min(delayMs, opts.maxDelayMs);
      await delay(capped);
      delayMs *= 2;
    }
  }

  throw lastError;
}
