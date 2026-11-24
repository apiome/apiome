/**
 * A small in-process cache for the public directory's global reads (DBP-1.16, #7199).
 *
 * The directory statistics in the navbar and the home page's rails are the same for every visitor
 * and cost a pass over the whole public catalog. They are read through {@link cachedRead}, so one
 * Browse process runs each of them at most once per {@link browseCacheTtlMs} instead of once per
 * page view.
 *
 * What a caller gets:
 *
 *   - **Fresh for the interval.** A value younger than the interval is returned without a query.
 *   - **One load at a time.** Concurrent callers of an expired key share one query.
 *   - **Failures are not cached.** When the loader throws, the previous value is served if there
 *     is one (stale beats empty for a counter); otherwise the error reaches the caller, which
 *     applies its own fallback. The next call tries the loader again.
 *
 * The cache is per process: each Browse instance refreshes on its own clock, so two instances can
 * disagree for up to one interval. Values are returned by reference — callers must not mutate them.
 *
 * A second, separate instance ({@link searchFacetCache}) remembers the filter facets of recent
 * searches, so a visitor paging through results does not recount them; it is separate so that a
 * burst of searches can never push the directory's own entries out.
 */

/** Default refresh interval, in seconds. */
export const DEFAULT_BROWSE_CACHE_TTL_SECONDS = 120;

/** Longest refresh interval `BROWSE_CACHE_TTL_SECONDS` may ask for, in seconds. */
export const MAX_BROWSE_CACHE_TTL_SECONDS = 300;

/** Options of one cache call. */
export interface CacheCallOptions {
  /** The interval for this call, in milliseconds; defaults to {@link browseCacheTtlMs}. */
  ttlMs?: number;
  /** The clock, in epoch milliseconds; injectable for tests. */
  now?: () => number;
  /**
   * Whether a failed refresh may return the previous (expired) value. Default true: stale beats
   * empty for a counter. Pass false where an expired value must not be acted on (the Try It
   * relay's allow-policy): the loader's error then reaches the caller.
   */
  staleOnError?: boolean;
}

interface Entry {
  /** The last loaded value. */
  value?: unknown;
  /** Whether `value` holds a loaded value (it may legitimately be `undefined` or `null`). */
  loaded: boolean;
  /** Epoch milliseconds after which `value` is stale. */
  expiresAt: number;
  /** The load in flight, shared by concurrent callers. */
  pending?: Promise<unknown>;
}

/**
 * The refresh interval for the directory cache.
 *
 * @returns Milliseconds, from `BROWSE_CACHE_TTL_SECONDS` (default 120, at most 300). `0` turns the
 *   cache off: every call runs its loader. A value that is not a whole number ≥ 0 means the default.
 */
export function browseCacheTtlMs(): number {
  const raw = (process.env.BROWSE_CACHE_TTL_SECONDS ?? '').trim();
  const parsed = /^\d+$/.test(raw) ? Number.parseInt(raw, 10) : DEFAULT_BROWSE_CACHE_TTL_SECONDS;
  return Math.min(parsed, MAX_BROWSE_CACHE_TTL_SECONDS) * 1000;
}

/** A bounded map of values that expire. See the module comment for the contract. */
export class TtlCache {
  private readonly entries = new Map<string, Entry>();

  /**
   * @param maxEntries - Most keys held; the entry stored longest ago is dropped past this.
   */
  constructor(private readonly maxEntries: number) {}

  /** The entry for a key, created (evicting the oldest when full) if missing. */
  private entryFor(key: string): Entry {
    let entry = this.entries.get(key);
    if (!entry) {
      if (this.entries.size >= this.maxEntries) {
        const oldest = this.entries.keys().next().value;
        if (oldest !== undefined) this.entries.delete(oldest);
      }
      entry = { loaded: false, expiresAt: 0 };
      this.entries.set(key, entry);
    }
    return entry;
  }

  /**
   * Read a value through the cache.
   *
   * @param key - Identifies the read *and its arguments* (`'home-project-rail:versions:8'`).
   * @param loader - Loads the value. It must throw on failure rather than return a fallback, so a
   *   failure is never stored.
   * @param options - See {@link CacheCallOptions}.
   * @returns The cached or freshly loaded value.
   * @throws Whatever the loader throws, when there is no earlier value to serve instead.
   */
  async read<T>(key: string, loader: () => Promise<T>, options: CacheCallOptions = {}): Promise<T> {
    const ttlMs = options.ttlMs ?? browseCacheTtlMs();
    if (ttlMs <= 0) return loader();
    const now = options.now ?? Date.now;

    const existing = this.entries.get(key);
    if (existing?.loaded && now() < existing.expiresAt) return existing.value as T;
    if (existing?.pending) return existing.pending as Promise<T>;

    const entry = this.entryFor(key);
    entry.pending = (async () => {
      try {
        const value = await loader();
        entry.value = value;
        entry.loaded = true;
        entry.expiresAt = now() + ttlMs;
        return value;
      } catch (err) {
        if (entry.loaded && options.staleOnError !== false) {
          const e = err as { message?: string };
          console.error(`[db] ${key}: refresh failed, serving the previous value:`, e?.message ?? err);
          return entry.value;
        }
        if (this.entries.get(key) === entry) this.entries.delete(key);
        throw err;
      } finally {
        entry.pending = undefined;
      }
    })();
    return entry.pending as Promise<T>;
  }

  /**
   * The fresh value stored under a key, without loading.
   *
   * @returns `{ value }` when a value younger than its interval is held, otherwise `undefined`.
   */
  peek<T>(key: string, options: Pick<CacheCallOptions, 'now'> = {}): { value: T } | undefined {
    const entry = this.entries.get(key);
    const now = options.now ?? Date.now;
    return entry?.loaded && now() < entry.expiresAt ? { value: entry.value as T } : undefined;
  }

  /**
   * Store a value the caller already has. Does nothing when the cache is off (interval 0).
   *
   * @param key - The key to store under.
   * @param value - The value.
   * @param options - See {@link CacheCallOptions}.
   */
  store<T>(key: string, value: T, options: CacheCallOptions = {}): void {
    const ttlMs = options.ttlMs ?? browseCacheTtlMs();
    if (ttlMs <= 0) return;
    const entry = this.entryFor(key);
    entry.value = value;
    entry.loaded = true;
    entry.expiresAt = (options.now ?? Date.now)() + ttlMs;
  }

  /** Drop every value. */
  clear(): void {
    this.entries.clear();
  }
}

/** The directory's global reads: statistics and home rails. A handful of keys. */
export const directoryCache = new TtlCache(64);

/** Filter facets of recent searches, keyed by the search without its page number. */
export const searchFacetCache = new TtlCache(256);

/**
 * Read one of the directory's global values through {@link directoryCache}.
 *
 * @param key - Identifies the read and its arguments.
 * @param loader - Loads the value; must throw on failure.
 * @param options - See {@link CacheCallOptions}.
 * @returns The cached or freshly loaded value.
 */
export function cachedRead<T>(key: string, loader: () => Promise<T>, options: CacheCallOptions = {}): Promise<T> {
  return directoryCache.read(key, loader, options);
}

/** Drop every cached value. For tests. */
export function clearBrowseCache(): void {
  directoryCache.clear();
  searchFacetCache.clear();
}
