/**
 * Same-origin request check for state-changing route handlers (OLO-7.3 follow-up, #4963).
 *
 * A route that changes state on behalf of the signed-in user must not be reachable from another
 * site: the browser attaches the session cookie to a cross-site request, so the cookie alone does
 * not prove the user meant to make it. Browsers send an `Origin` header on every `fetch` that is
 * not a plain GET/HEAD, and a page cannot forge it, so comparing it with the `Host` the request
 * was sent to tells a call from this app's own pages from one another site triggered.
 *
 * Use it on POST / PUT / PATCH / DELETE handlers only. A top-level navigation and a same-origin
 * GET carry no `Origin`, so a GET handler guarded this way would refuse its own callers — which is
 * also why a route that needs this guard must not be a GET in the first place.
 */

/** The request headers the check reads; `Headers` and `NextRequest.headers` both satisfy it. */
export interface OriginCheckHeaders {
  get(name: string): string | null;
}

/**
 * Whether a request was sent by a page of the origin it was sent to.
 *
 * @param headers The incoming request's headers.
 * @returns `true` only when `Origin` is present, parses as a URL, and its host (hostname plus
 *   port) equals the `Host` header. A missing or malformed `Origin`, a missing `Host`, and
 *   `Origin: null` (sandboxed frames, some redirects) all yield `false` — refuse when unsure.
 */
export function isSameOriginRequest(headers: OriginCheckHeaders): boolean {
  const origin = headers.get('origin');
  const host = headers.get('host');
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host.trim().toLowerCase();
  } catch {
    return false;
  }
}
