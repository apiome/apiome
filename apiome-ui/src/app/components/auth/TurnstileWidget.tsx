'use client';

/**
 * Cloudflare Turnstile widget for the email sign-up form (SGN-1.5, #5654).
 *
 * Drawn only when the installation sets both `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`
 * (`lib/auth/turnstile.ts`); the `/signup` page passes the public site key down. The widget loads
 * Cloudflare's script once per page, renders explicitly into its own element and reports each
 * token (or its loss — expiry, error) through `onToken`. A token works once, so the form bumps
 * `resetKey` after every submission to get a fresh one.
 */

import { useEffect, useRef } from 'react';

import { TURNSTILE_SCRIPT_URL } from '@lib/auth/turnstile';

/** The slice of Cloudflare's `window.turnstile` API this widget uses. */
interface TurnstileApi {
  render: (
    element: HTMLElement,
    options: {
      sitekey: string;
      theme?: 'auto' | 'light' | 'dark';
      callback: (token: string) => void;
      'expired-callback': () => void;
      'error-callback': () => void;
    },
  ) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** One script load shared by every widget on the page. */
let scriptLoad: Promise<TurnstileApi> | null = null;

/**
 * Load Cloudflare's script (once) and resolve its API.
 *
 * @returns The `window.turnstile` API; rejects when the script cannot load.
 */
function loadTurnstile(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!scriptLoad) {
    scriptLoad = new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = TURNSTILE_SCRIPT_URL;
      script.async = true;
      script.defer = true;
      script.onload = () =>
        window.turnstile ? resolve(window.turnstile) : reject(new Error('Turnstile did not load'));
      script.onerror = () => {
        scriptLoad = null;
        reject(new Error('Turnstile did not load'));
      };
      document.head.appendChild(script);
    });
  }
  return scriptLoad;
}

/** Props for {@link TurnstileWidget}. */
export interface TurnstileWidgetProps {
  /** The public `TURNSTILE_SITE_KEY`. */
  siteKey: string;
  /** Called with each new token, and with null when the token expires or the check errors. */
  onToken: (token: string | null) => void;
  /** Change it to reset the widget and get a fresh token (after a submission). */
  resetKey?: number;
}

/**
 * The widget.
 *
 * @param props See {@link TurnstileWidgetProps}.
 * @returns The element Cloudflare draws into.
 */
export function TurnstileWidget({ siteKey, onToken, resetKey = 0 }: TurnstileWidgetProps) {
  const container = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  // The latest callback, so a re-render does not redraw the widget.
  const tokenCallback = useRef(onToken);
  useEffect(() => {
    tokenCallback.current = onToken;
  }, [onToken]);

  useEffect(() => {
    let cancelled = false;
    loadTurnstile()
      .then((api) => {
        if (cancelled || !container.current) return;
        widgetId.current = api.render(container.current, {
          sitekey: siteKey,
          theme: 'auto',
          callback: (token) => tokenCallback.current(token),
          'expired-callback': () => tokenCallback.current(null),
          'error-callback': () => tokenCallback.current(null),
        });
      })
      .catch(() => tokenCallback.current(null));
    return () => {
      cancelled = true;
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [siteKey]);

  useEffect(() => {
    if (resetKey > 0 && widgetId.current && window.turnstile) {
      window.turnstile.reset(widgetId.current);
      tokenCallback.current(null);
    }
  }, [resetKey]);

  return <div ref={container} className="flex justify-center" data-testid="signup-turnstile" />;
}

export default TurnstileWidget;
