/**
 * A small in-process cache whose entries expire (DBP-1.15, #7198).
 *
 * Used for Home's dashboard counters: a reader who opens Home again within the cache age gets the
 * counts they were last shown without a database round-trip. Each UI server process keeps its own
 * entries; nothing is shared between processes or survives a restart.
 *
 * The cache is bounded: when it is full, the oldest entry is dropped to make room, so a busy
 * server cannot grow it without limit.
 *
 * Deliberately **not** a `'use server'` module.
 */

/** A cached value and the time it stops being served. */
interface Entry<V> {
  value: V;
  expiresAt: number;
}

/** A bounded cache of values that expire `ttlMs` after they are stored. */
export class TtlCache<V> {
  private readonly entries = new Map<string, Entry<V>>();

  /**
   * @param ttlMs How long a stored value is served, in milliseconds.
   * @param maxEntries The most entries kept; the oldest is dropped beyond it.
   * @param now The clock — `Date.now` outside tests.
   */
  constructor(
    private readonly ttlMs: number,
    private readonly maxEntries: number,
    private readonly now: () => number = Date.now
  ) {}

  /**
   * The value stored for `key`, if it has not expired.
   *
   * @param key The entry's key.
   * @returns The value, or `undefined` when missing or expired (an expired entry is removed).
   */
  get(key: string): V | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(key);
      return undefined;
    }
    return entry.value;
  }

  /**
   * Store `value` for `key`, served until the cache age has passed.
   *
   * @param key The entry's key.
   * @param value The value to serve.
   */
  set(key: string, value: V): void {
    this.entries.delete(key);
    while (this.entries.size >= Math.max(1, this.maxEntries)) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
    this.entries.set(key, { value, expiresAt: this.now() + this.ttlMs });
  }

  /**
   * Drop the entry for `key`, so the next read computes it afresh.
   *
   * @param key The entry's key.
   */
  delete(key: string): void {
    this.entries.delete(key);
  }

  /** Drop every entry. */
  clear(): void {
    this.entries.clear();
  }
}
