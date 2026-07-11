'use client';

/**
 * Loads the GOV-1.2 rule catalog (and optional custom-rule descriptions) for violation display.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { styleGuidesApi, type GuideCustomRulesView } from '@/app/ade/dashboard/style-guides/api';
import {
  customRuleDescriptionsFromYaml,
  fetchLintRuleCatalog,
  type LintRuleCatalog,
} from '@/app/utils/lint-rule-catalog';

export interface UseLintViolationContextResult {
  catalog: LintRuleCatalog | null;
  customDescriptions: Map<string, string>;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

export function useLintViolationContext(
  guideId?: string | null,
  enabled = true,
): UseLintViolationContextResult {
  const [catalog, setCatalog] = useState<LintRuleCatalog | null>(null);
  const [customDescriptions, setCustomDescriptions] = useState<Map<string, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const retry = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const loadedCatalog = await fetchLintRuleCatalog({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setCatalog(loadedCatalog);

        let custom = new Map<string, string>();
        const gid = (guideId || '').trim();
        if (gid) {
          try {
            const view = await styleGuidesApi<GuideCustomRulesView>(`${gid}/custom-rules`, {
              signal: controller.signal,
            });
            if (!controller.signal.aborted && view?.yaml) {
              custom = customRuleDescriptionsFromYaml(view.yaml);
            }
          } catch {
            /* custom rules are best-effort — built-in catalog still enriches most findings */
          }
        }
        if (!controller.signal.aborted) {
          setCustomDescriptions(custom);
          setLoading(false);
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Failed to load lint rule catalog');
        setLoading(false);
      }
    })();

    return () => controller.abort();
  }, [guideId, reloadToken, enabled]);

  return useMemo(
    () => ({ catalog, customDescriptions, loading, error, retry }),
    [catalog, customDescriptions, loading, error, retry],
  );
}
