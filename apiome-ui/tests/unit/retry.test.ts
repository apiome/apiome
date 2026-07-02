/**
 * Tests for the retry utility (error recovery strategy).
 * Covers withRetry, isTransientError, and retry options.
 */

import { describe, test, expect, jest } from '@jest/globals';
import { withRetry, isTransientError } from '../../lib/retry';

describe('retry - isTransientError', () => {
  test('returns true for ECONNREFUSED', () => {
    expect(isTransientError(new Error('ECONNREFUSED'))).toBe(true);
    expect(isTransientError(new Error('connect ECONNREFUSED 127.0.0.1:5432'))).toBe(true);
  });

  test('returns true for ECONNRESET', () => {
    expect(isTransientError(new Error('ECONNRESET'))).toBe(true);
  });

  test('returns true for ETIMEDOUT', () => {
    expect(isTransientError(new Error('ETIMEDOUT'))).toBe(true);
  });

  test('returns true for connection/timeout/network keywords', () => {
    expect(isTransientError(new Error('connection refused'))).toBe(true);
    expect(isTransientError(new Error('Request timeout'))).toBe(true);
    expect(isTransientError(new Error('network error'))).toBe(true);
  });

  test('returns true for deadlock/serialization DB errors', () => {
    expect(isTransientError(new Error('deadlock detected'))).toBe(true);
    expect(isTransientError(new Error('serialization failure'))).toBe(true);
    expect(isTransientError(new Error('could not obtain lock'))).toBe(true);
  });

  test('returns false for validation or business logic errors', () => {
    expect(isTransientError(new Error('Invalid schema'))).toBe(false);
    expect(isTransientError(new Error('Project already exists'))).toBe(false);
    expect(isTransientError(new Error('Tenant ID is required'))).toBe(false);
    expect(isTransientError(new Error('Unique constraint violation'))).toBe(false);
  });

  test('returns false for null/undefined', () => {
    expect(isTransientError(null)).toBe(false);
    expect(isTransientError(undefined)).toBe(false);
  });

  test('returns false for non-object throwables (string)', () => {
    // Only object-like errors are inspected for message; strings return false
    expect(isTransientError('connection lost')).toBe(false);
    expect(isTransientError('validation failed')).toBe(false);
  });
});

describe('retry - withRetry', () => {
  test('returns result on first successful call', async () => {
    const fn = jest.fn().mockResolvedValue(42);
    const promise = withRetry(fn, { maxAttempts: 3, initialDelayMs: 100 });
    const result = await promise;
    expect(result).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('retries on transient error and succeeds on second attempt', async () => {
    const fn = jest.fn()
      .mockRejectedValueOnce(new Error('ECONNREFUSED'))
      .mockResolvedValueOnce('ok');
    const promise = withRetry(fn, { maxAttempts: 3, initialDelayMs: 100 });
    const result = await promise;
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(2);
  });

  test('retries up to maxAttempts then throws last error', async () => {
    const err = new Error('ETIMEDOUT');
    const fn = jest.fn().mockRejectedValue(err);
    const promise = withRetry(fn, { maxAttempts: 3, initialDelayMs: 10 });
    await expect(promise).rejects.toThrow('ETIMEDOUT');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  test('does not retry when error is not transient (default isRetryable)', async () => {
    const fn = jest.fn().mockRejectedValue(new Error('Invalid schema'));
    const promise = withRetry(fn, { maxAttempts: 3 });
    await expect(promise).rejects.toThrow('Invalid schema');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('respects custom isRetryable returning false', async () => {
    const fn = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const promise = withRetry(fn, {
      maxAttempts: 3,
      isRetryable: () => false
    });
    await expect(promise).rejects.toThrow('ECONNREFUSED');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('respects custom isRetryable returning true for non-transient error', async () => {
    const fn = jest.fn()
      .mockRejectedValueOnce(new Error('Invalid schema'))
      .mockResolvedValueOnce('recovered');
    const promise = withRetry(fn, {
      maxAttempts: 3,
      initialDelayMs: 10,
      isRetryable: () => true
    });
    const result = await promise;
    expect(result).toBe('recovered');
    expect(fn).toHaveBeenCalledTimes(2);
  });

  test('respects maxAttempts option', async () => {
    const fn = jest.fn().mockRejectedValue(new Error('timeout'));
    const promise = withRetry(fn, { maxAttempts: 5, initialDelayMs: 10 });
    await expect(promise).rejects.toThrow('timeout');
    expect(fn).toHaveBeenCalledTimes(5);
  });

  test('with maxAttempts 1 does not retry', async () => {
    const fn = jest.fn().mockRejectedValue(new Error('connection failed'));
    const promise = withRetry(fn, { maxAttempts: 1 });
    await expect(promise).rejects.toThrow('connection failed');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('succeeds on third attempt after two transient failures', async () => {
    const fn = jest.fn()
      .mockRejectedValueOnce(new Error('ECONNRESET'))
      .mockRejectedValueOnce(new Error('ETIMEDOUT'))
      .mockResolvedValueOnce('ok');
    const promise = withRetry(fn, { maxAttempts: 3, initialDelayMs: 1, maxDelayMs: 10 });
    const result = await promise;
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(3);
  });
});
