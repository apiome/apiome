'use client';

/**
 * **Suggested consumers** on a project's Dependencies tab (CDG-3.5, #5970).
 *
 * Clients seen in the project's traffic that no binding attributes to a registered consumer: by the
 * product token of their user agent (`checkout-web`), or — for a header, API key or JWT claim the
 * edge hashed — by the kind of credential and an opaque tag, never the value or its hash. **Register
 * consumer** opens a short dialog and registers it in the consumer registry together with the
 * binding that recognises it, so its next calls draw runtime edges here.
 *
 * Renders nothing when there is nothing to suggest, or when the read is refused (a viewer without
 * `consumer_contracts:view`): the Dependencies list above it must never fail because of it.
 */

import * as React from 'react';
import { UserPlus } from 'lucide-react';
import { Alert, Badge, Button, Input, Label, Spinner } from '@/app/components/ui';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { toast } from '@/app/components/ui/toast';
import { SUGGESTION_KIND_LABELS, suggestionMetaLine, type SuggestedConsumer } from '@lib/graph';
import { fetchSuggestedConsumers, registerSuggestedConsumer } from './graphApi';

export interface SuggestedConsumersProps {
  /** The project or catalog item whose traffic is read. */
  projectId: string;
  /** Load only once the tab is shown. */
  active: boolean;
  /** Called after a registration, so the page can re-read its edges. */
  onRegistered?: () => void;
}

interface Draft {
  name: string;
  slug: string;
  bindingName: string;
}

/**
 * The register dialog for one suggestion.
 *
 * @param props - The suggestion (or `null` when closed), close, and the submit.
 * @returns The dialog.
 */
function RegisterDialog({
  suggestion,
  onClose,
  onSubmit,
}: {
  suggestion: SuggestedConsumer | null;
  onClose: () => void;
  onSubmit: (draft: Draft) => Promise<string | null>;
}) {
  const [draft, setDraft] = React.useState<Draft>({
    name: '',
    slug: '',
    bindingName: '',
  });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!suggestion) return;
    setDraft({
      name: suggestion.suggested_name,
      slug: suggestion.suggested_slug ?? '',
      bindingName: '',
    });
    setError('');
  }, [suggestion]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) {
      setError('Enter a name.');
      return;
    }
    if (suggestion?.needs_binding_name && !draft.bindingName.trim()) {
      setError('Enter the header or claim the value arrives in.');
      return;
    }
    setBusy(true);
    const failure = await onSubmit(draft);
    setBusy(false);
    if (failure) setError(failure);
  };

  return (
    <Dialog open={suggestion !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="dg-suggest-dialog" data-testid="register-suggestion-dialog">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Register a suggested consumer</DialogTitle>
            <DialogDescription>
              {suggestion?.client_kind === 'user_agent'
                ? `Calls whose user agent starts with ${suggestion.label}/ will be attributed to it.`
                : 'Calls carrying this value will be attributed to it. The value itself is never shown.'}
            </DialogDescription>
          </DialogHeader>
          <div className="dg-suggest-dialog__fields">
            <div className="dg-suggest-dialog__field">
              <Label htmlFor="suggestion-name">Name</Label>
              <Input
                id="suggestion-name"
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </div>
            <div className="dg-suggest-dialog__field">
              <Label htmlFor="suggestion-slug">Handle</Label>
              <Input
                id="suggestion-slug"
                value={draft.slug}
                placeholder="Derived from the name"
                spellCheck={false}
                onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
              />
            </div>
            {suggestion?.needs_binding_name ? (
              <div className="dg-suggest-dialog__field">
                <Label htmlFor="suggestion-binding">Header or claim name</Label>
                <Input
                  id="suggestion-binding"
                  value={draft.bindingName}
                  placeholder={suggestion.client_kind === 'jwt_claim' ? 'azp' : 'x-api-key'}
                  spellCheck={false}
                  onChange={(event) => setDraft({ ...draft, bindingName: event.target.value })}
                />
              </div>
            ) : null}
            {error ? <Alert variant="danger">{error}</Alert> : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? <Spinner aria-hidden /> : null}
              Register consumer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function SuggestedConsumers({ projectId, active, onRegistered }: SuggestedConsumersProps) {
  const [suggestions, setSuggestions] = React.useState<SuggestedConsumer[]>([]);
  const [registering, setRegistering] = React.useState<SuggestedConsumer | null>(null);
  // The button is offered only to a caller REST would let register (`consumer_contracts:create`).
  const [canRegister, setCanRegister] = React.useState(false);

  React.useEffect(() => {
    if (!active) return;
    fetch('/api/access/permissions/me')
      .then((response) => response.json())
      .then((body) => {
        const data = body?.success ? (body.data as { is_admin?: boolean; permissions?: string[] }) : null;
        setCanRegister(Boolean(data?.is_admin || data?.permissions?.includes('consumer_contracts:create')));
      })
      .catch(() => setCanRegister(false));
  }, [active]);

  const load = React.useCallback(async () => {
    try {
      setSuggestions(await fetchSuggestedConsumers(projectId));
    } catch {
      setSuggestions([]);
    }
  }, [projectId]);

  React.useEffect(() => {
    if (active) void load();
  }, [active, load]);

  const register = async (draft: Draft): Promise<string | null> => {
    if (!registering) return null;
    try {
      const result = await registerSuggestedConsumer(projectId, registering.id, {
        name: draft.name.trim(),
        ...(draft.slug.trim() ? { slug: draft.slug.trim() } : {}),
        ...(registering.needs_binding_name ? { binding_name: draft.bindingName.trim() } : {}),
      });
      toast.success(`${result.consumer.name} registered`);
      setRegistering(null);
      await load();
      onRegistered?.();
      return null;
    } catch (caught) {
      return caught instanceof Error && caught.message ? caught.message : 'The consumer could not be registered';
    }
  };

  if (!active || suggestions.length === 0) return null;
  return (
    <section className="dg-suggest" aria-labelledby={`dg-suggest-${projectId}`} data-testid="suggested-consumers">
      <h3 id={`dg-suggest-${projectId}`} className="dg-group__title">
        Suggested consumers
        <span className="dg-group__count">{suggestions.length}</span>
      </h3>
      <p className="dg-suggest__intro">
        Seen calling this API in the last 30 days, but not registered. Register one to attribute its calls.
      </p>
      <ul className="dg-suggest__list">
        {suggestions.map((suggestion) => (
          <li key={suggestion.id} className="dg-suggest__item" data-testid={`suggested-consumer-${suggestion.id}`}>
            <Badge variant="neutral">{SUGGESTION_KIND_LABELS[suggestion.client_kind]}</Badge>
            <span className="dg-suggest__name">
              <span className="dg-suggest__label">{suggestion.label}</span>
              <span className="dg-suggest__meta">{suggestionMetaLine(suggestion)}</span>
            </span>
            {canRegister ? (
              <Button type="button" variant="secondary" size="sm" onClick={() => setRegistering(suggestion)}>
                <UserPlus aria-hidden />
                Register consumer
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      <RegisterDialog suggestion={registering} onClose={() => setRegistering(null)} onSubmit={register} />
    </section>
  );
}
