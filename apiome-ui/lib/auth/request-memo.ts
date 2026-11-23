/**
 * Per-request memoization for server-side reads (DBP-1.15, #7198).
 *
 * A single page render or server action asks for the session, the caller's tenant membership, the
 * tenant slug and the caller's grants many times — once per guard, per section, per helper. Each ask
 * used to be a fresh round-trip. {@link requestMemo} makes the second and later asks in the same
 * request reuse the first answer.
 *
 * **Scope.** Answers are kept against the request's `headers()` object, which Next.js creates once
 * per incoming request and resolves to the same object for every `await headers()` in that request
 * — Server Components, server actions and route handlers alike. The store is a `WeakMap`, so the
 * answers are dropped with the request. `React.cache` is not used because it only memoizes inside a
 * React render, not inside a server action or a route handler.
 *
 * **Cookie changes.** A server action may sign the caller in or out, or switch the active tenant, and
 * then the page re-renders in the same request. The key therefore includes the request's current
 * cookies (`cookies().toString()`, which reflects cookies set earlier in the request), so a read made
 * after such a change is computed afresh instead of returning the old answer.
 *
 * **Outside a request** (unit tests, scripts, a background job) `headers()` throws; the function
 * then simply runs `load` every time — the behaviour before this module existed.
 *
 * A rejected `load` is not kept, so a transient failure is retried by the next ask.
 *
 * Deliberately **not** a `'use server'` module.
 */

/** The answers kept for one request: `<namespace>\u0000<key>\u0000<cookies>` → pending answer. */
type RequestAnswers = Map<string, Promise<unknown>>;

/** One entry per live request, keyed by that request's `headers()` object. */
const store = new WeakMap<object, RequestAnswers>();

/**
 * The current request's scope object and cookie signature, or `null` outside a request.
 *
 * @returns The `headers()` object and the serialized cookies, or `null`.
 */
async function currentRequest(): Promise<{ scope: object; cookies: string } | null> {
  try {
    const { headers, cookies } = await import('next/headers');
    const scope = (await headers()) as unknown;
    if (!scope || typeof scope !== 'object') return null;
    let cookieSignature = '';
    try {
      cookieSignature = String((await cookies()).toString());
    } catch {
      cookieSignature = '';
    }
    return { scope, cookies: cookieSignature };
  } catch {
    return null;
  }
}

/**
 * Run `load` at most once per request for the given namespace and key.
 *
 * @param namespace What is being read, e.g. `'session'` or `'tenant-slug'`; keeps keys apart.
 * @param key The read's arguments, already turned into a string (e.g. `"<tenant>:<user>"`).
 * @param load Computes the answer. Called again for a later ask only if an earlier call rejected,
 *   the cookies changed, or there is no request scope.
 * @returns The answer — shared by every ask in the request.
 */
export async function requestMemo<T>(namespace: string, key: string, load: () => Promise<T>): Promise<T> {
  const request = await currentRequest();
  if (!request) return load();

  let answers = store.get(request.scope);
  if (!answers) {
    answers = new Map();
    store.set(request.scope, answers);
  }
  const slot = `${namespace}\u0000${key}\u0000${request.cookies}`;
  const existing = answers.get(slot) as Promise<T> | undefined;
  if (existing) return existing;

  const pending = load();
  answers.set(slot, pending);
  // Forget a failure so the next ask retries; the caller still sees this rejection.
  pending.catch(() => {
    if (answers?.get(slot) === pending) answers.delete(slot);
  });
  return pending;
}
