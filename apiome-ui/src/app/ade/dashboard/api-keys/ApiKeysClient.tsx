'use client';

import * as React from 'react';
import { BookOpen, KeyRound, Lock, Plus } from 'lucide-react';

import { useAuthSession } from '@lib/auth/session-client';
import { loadTenantMembershipContext } from '@lib/auth/tenant-membership-context';
import type { ShortcutBinding } from '@lib/shortcuts';
import { useShortcuts } from '@/app/hooks/useShortcuts';

import {
  createMcpKey,
  fetchMcpKeys,
  regenerateMcpKey,
  revokeMcpKey,
  type McpApiKeyMetadata,
} from '@/app/ade/dashboard/tenants/mcpKeysApi';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { OPEN_ACTIONS, useOpenAction } from '@/app/components/shell/openActions';
import {
  apiKeyExpiryNotice,
  createApiKeyForTenant,
  describeCreatedApiKey,
  displayApiKeyPrefix,
  fetchApiKeys,
  parseApiKeyExpiry,
  regenerateApiKeySecret,
  removeApiKey,
  scopesForApiKeyPreset,
  setApiKeyEnabled,
  ApiKeyReferenceCards,
  ApiKeySecretDialog,
  CreateApiKeyDialog,
  CreateMcpKeyDialog,
  DeleteApiKeyDialog,
  DisableApiKeyDialog,
  McpKeyReferenceCard,
  RegenerateKeyDialog,
  RevokeMcpKeyDialog,
  WorkspaceKeysTable,
  describeCreatedMcpKey,
  describeRegeneratedKey,
  mcpKeyExpiresAt,
  toWorkspaceKeyRows,
  workspaceKeyName,
  workspaceKeyPrefix,
  workspaceKeyRowId,
  WORKSPACE_KEY_KIND_LABEL,
  type ApiKeyDraft,
  type ApiKeyRecord,
  type McpKeyDraft,
  type WorkspaceKeyRow,
} from '@/app/components/ade/apiKeys';

/**
 * API keys — `/ade/dashboard/api-keys` (HIVE-5.4, #5307).
 *
 * Authority: `docs/mockups/workspace/api-keys.html`, whose **Notes → Keeps (1:1)** list is
 * this ticket's acceptance criteria; DESIGN.md §5.3 (page header), §7 (dialogs), §8 (list).
 *
 * ### What this page owns
 *
 * The keys, the writes, and which overlay is open. How a key is *drawn* is
 * `WorkspaceKeysTable`, the create forms are `CreateApiKeyDialog` and `CreateMcpKeyDialog`,
 * the decisions are `DisableApiKeyDialog`, `DeleteApiKeyDialog`, `RevokeMcpKeyDialog` and
 * `RegenerateKeyDialog`, and the one-time reveal is `ApiKeySecretDialog` — which is the only
 * component on this page that ever holds a plaintext key, and holds it for exactly as long as
 * its dialog is open.
 *
 * ### The secret's life, stated in one place
 *
 * A create or a regenerate resolves with the plaintext key; it goes into {@link secret},
 * which the reveal dialog renders. Closing that dialog is the *only* transition out, and it
 * clears the value. There is no code path that puts a secret back — no re-reveal button, no
 * cached copy in the table, no query parameter — which is what makes the ticket's first
 * acceptance criterion structural rather than a promise.
 *
 * ### Two kinds of key, one list
 *
 * **REST API** keys call the REST API (`api_keys`); **MCP server** keys are what agents and MCP
 * hosts call Apiome's MCP server with (`mcp_api_keys`). The server accepts neither in place of
 * the other, but both are the workspace's API keys, so they share one table with a Type column
 * and a Type filter — a reader looking for "the API key" finds both in one place and is told
 * which kind each row is. The two lists load independently, so one failing read cannot empty
 * the other's rows. MCP keys are tenant-admin only on the server; a member sees the REST keys
 * and a sentence saying where MCP keys come from, rather than a refused read. The manage
 * drawer's MCP section still lists, creates and regenerates MCP keys too.
 *
 * ### Regenerate rather than delete and re-create
 *
 * Every live key can be **regenerated**: its secret is replaced in place and the id, name,
 * scopes or tools, switch and expiry carry over. The old secret is refused from its next
 * request, and the new one goes through the same reveal-once dialog as a new key's.
 *
 * ### Errors are the overlay's, the load's error is the table's
 *
 * Every write hands its failure back to the dialog that asked for it, so the message appears
 * beside the control that caused it rather than in a banner behind an overlay. The load's
 * failure goes into the table, as `DataTable`'s own error state with a retry — the screen
 * this replaces answered a failed read with an empty table and the words "No API Keys Yet",
 * which is a claim about the workspace rather than about the request.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** Where the reader picks a workspace, for the no-tenant state. */
const TENANTS_ROUTE = '/ade/dashboard/tenants';

/** The REST reference, which the header's secondary action opens. */
const API_DOCS_ROUTE = '/ade/dashboard/help';

/** The header's one line, for both tabs. */
const PAGE_DESCRIPTION =
  'Keys for the REST API and for agents calling the MCP server. Prefer scoped CI tokens for pipelines.';

/** What the workspace is called before its name is known. */
const FALLBACK_TENANT_NAME = 'this workspace';

/**
 * The page's own `N`, registered only while creating is possible.
 *
 * HIVE-3.7's registry is explicit that a list page owning a better `N` registers over the
 * shell's generic one for as long as it is mounted — and that a chip promising a chord which
 * does not fire is the thing the registry exists to prevent, which is why this is not
 * declared while the page has no tenant to create a key in.
 */
const CREATE_SHORTCUT_ID = 'api-keys-create';

/** Which overlay, if any, is open over the page. */
type ApiKeyOverlay =
  | 'none'
  | 'create'
  | 'disable'
  | 'delete'
  | 'mcp-create'
  | 'mcp-revoke'
  | 'regenerate';

/**
 * Whether the reader may manage this workspace's MCP keys.
 *
 * `pending` until the membership context answers; `unverified` when it could not, in which
 * case the list is read anyway and the server's answer decides.
 */
type McpKeyAccess = 'pending' | 'admin' | 'member' | 'unverified';

/**
 * Turn a caught write failure into the sentence to show.
 *
 * @param error Whatever was caught.
 * @param fallback What to say when the failure carried no message.
 * @returns The sentence.
 */
function describeFailure(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * The API keys page.
 *
 * @returns The header, the expiry banner, the keys table, the reference cards and the four
 *   overlays.
 */
export default function ApiKeysClient() {
  const { data: session } = useAuthSession();
  const currentTenantId = (session?.user as { current_tenant_id?: string } | undefined)
    ?.current_tenant_id;

  const [keys, setKeys] = React.useState<ApiKeyRecord[]>([]);
  const [loading, setLoading] = React.useState(true);
  /**
   * Why the list could not be read.
   *
   * Kept apart from {@link writeError} because the two belong in different places, the split
   * `MembersClient` settled on. A load failure leaves the table with nothing to draw, and a
   * table with nothing to draw says "No API keys yet" — a claim about the workspace rather
   * than about the request. It therefore goes *into* the card, as `DataTable`'s own error
   * state with a retry beside it.
   */
  const [loadError, setLoadError] = React.useState<string | null>(null);
  /**
   * A write that failed with no dialog open to report into.
   *
   * There is exactly one: turning a key back **on**, which is immediate. Every other write
   * happens behind an overlay and reports there, beside the control that caused it.
   */
  const [writeError, setWriteError] = React.useState('');
  const [tenantName, setTenantName] = React.useState(FALLBACK_TENANT_NAME);
  /**
   * The moment status is judged against — expired or merely disabled.
   *
   * Owned by the page and refreshed on each load, so the banner at the top, the tint on a
   * row, the badge in it and the chip counts underneath cannot be judged against four
   * different instants. A key that expires while the tab is open is picked up by the next
   * load, which is also when its row could change for any other reason.
   */
  const [now, setNow] = React.useState(() => new Date());

  /** The row a write is running against (by `workspaceKeyRowId`), so only its controls go inert. */
  const [busyRowId, setBusyRowId] = React.useState<string | null>(null);
  const [overlay, setOverlay] = React.useState<ApiKeyOverlay>('none');
  /** Which key the open confirm is about. An id, so a reload refreshes what it shows. */
  const [overlayKeyId, setOverlayKeyId] = React.useState<string | null>(null);

  /**
   * The plaintext key, for as long as its dialog is open.
   *
   * `null` at every other moment, including immediately after the dialog closes. See the
   * module note above: this state is the whole of the reveal-once guarantee.
   */
  const [secret, setSecret] = React.useState<{
    value: string;
    summary: string;
    prefix: string;
    title: string;
  } | null>(null);

  const [mcpKeys, setMcpKeys] = React.useState<McpApiKeyMetadata[]>([]);
  const [mcpLoading, setMcpLoading] = React.useState(true);
  const [mcpLoadError, setMcpLoadError] = React.useState<string | null>(null);
  const [mcpAccess, setMcpAccess] = React.useState<McpKeyAccess>('pending');
  const [overlayMcpKeyId, setOverlayMcpKeyId] = React.useState<string | null>(null);
  /** Which row the regenerate confirm is about, by `workspaceKeyRowId`. */
  const [regenerateRowId, setRegenerateRowId] = React.useState<string | null>(null);

  const overlayMcpKey = React.useMemo(
    () => mcpKeys.find((key) => key.id === overlayMcpKeyId) ?? null,
    [mcpKeys, overlayMcpKeyId]
  );

  const overlayKey = React.useMemo(
    () => keys.find((key) => key.id === overlayKeyId) ?? null,
    [keys, overlayKeyId]
  );

  const rows = React.useMemo(() => toWorkspaceKeyRows(keys, mcpKeys), [keys, mcpKeys]);

  const regenerateRow = React.useMemo(
    () => rows.find((row) => workspaceKeyRowId(row) === regenerateRowId) ?? null,
    [rows, regenerateRowId]
  );

  // ---- load -----------------------------------------------------------------------------

  const loadKeys = React.useCallback(async () => {
    if (!currentTenantId) {
      setKeys([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      setKeys(await fetchApiKeys(currentTenantId));
      setNow(new Date());
    } catch (error) {
      setKeys([]);
      setLoadError(describeFailure(error, 'Failed to load API keys'));
    } finally {
      setLoading(false);
    }
  }, [currentTenantId]);

  React.useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  // The workspace's name is context, not content: it appears in the breadcrumb and in one
  // sentence on the reference card, and neither is worth failing the page for. A refused
  // read leaves the fallback wording in place. The same context says whether the reader
  // administers the workspace, which is what MCP keys need.
  React.useEffect(() => {
    if (!currentTenantId) return;
    let cancelled = false;
    loadTenantMembershipContext()
      .then((context) => {
        if (cancelled) return;
        const match = context.tenants.find((tenant) => tenant.id === currentTenantId);
        if (match?.name) setTenantName(match.name);
        setMcpAccess(context.adminTenantIds.includes(currentTenantId) ? 'admin' : 'member');
      })
      .catch(() => {
        /* The fallback name is already in place; the MCP read decides access itself. */
        if (!cancelled) setMcpAccess('unverified');
      });
    return () => {
      cancelled = true;
    };
  }, [currentTenantId]);

  const loadMcpKeys = React.useCallback(async () => {
    if (!currentTenantId || mcpAccess === 'pending') return;
    if (mcpAccess === 'member') {
      setMcpKeys([]);
      setMcpLoading(false);
      return;
    }
    setMcpLoading(true);
    setMcpLoadError(null);
    try {
      const list = await fetchMcpKeys();
      setMcpKeys(list.keys ?? []);
      setNow(new Date());
    } catch (error) {
      setMcpKeys([]);
      setMcpLoadError(describeFailure(error, 'Failed to load MCP keys'));
    } finally {
      setMcpLoading(false);
    }
  }, [currentTenantId, mcpAccess]);

  React.useEffect(() => {
    void loadMcpKeys();
  }, [loadMcpKeys]);

  // ---- writes ---------------------------------------------------------------------------

  const openCreate = React.useCallback(() => setOverlay('create'), []);
  const openMcpCreate = React.useCallback(() => setOverlay('mcp-create'), []);
  const canCreateMcp = mcpAccess !== 'member';

  /*
   * The command palette's "Create API key…" action (HIVE-3.6, #5292). The palette navigates
   * here with `?open=new-api-key`; this page opens the dialog it already owns, and
   * `useOpenAction` strips the parameter so a reload does not reopen it.
   */
  useOpenAction(OPEN_ACTIONS.newApiKey, openCreate);

  const createShortcuts = React.useMemo<readonly ShortcutBinding[]>(
    () =>
      currentTenantId
        ? [
            {
              id: CREATE_SHORTCUT_ID,
              scope: 'list',
              description: 'Create API key',
              chord: { key: 'n' },
              run: openCreate,
            },
          ]
        : [],
    [currentTenantId, openCreate]
  );
  useShortcuts(createShortcuts);

  const handleCreate = React.useCallback(
    async (draft: ApiKeyDraft): Promise<string | null> => {
      if (!currentTenantId) return 'Select a workspace before creating an API key.';
      try {
        const created = await createApiKeyForTenant({
          tenantId: currentTenantId,
          name: draft.name.trim(),
          description: draft.description.trim(),
          expiresInDays: parseApiKeyExpiry(draft.expiresInDays),
          scopes: scopesForApiKeyPreset(draft.preset),
        });
        setSecret({
          value: created.secret,
          summary: describeCreatedApiKey(draft),
          prefix: displayApiKeyPrefix(created.keyPrefix),
          title: 'API key created',
        });
        await loadKeys();
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to create API key');
      }
    },
    [currentTenantId, loadKeys]
  );

  /**
   * Run one write against one key, then reload.
   *
   * @param key The key the write is about.
   * @param fallback What to say if the failure carried no message.
   * @param write The call.
   * @returns `null` on success, or the sentence to show.
   */
  const runWrite = React.useCallback(
    async (
      key: ApiKeyRecord,
      fallback: string,
      write: () => Promise<void>
    ): Promise<string | null> => {
      setBusyRowId(workspaceKeyRowId({ kind: 'rest', key }));
      try {
        await write();
        await loadKeys();
        return null;
      } catch (error) {
        return describeFailure(error, fallback);
      } finally {
        setBusyRowId(null);
      }
    },
    [loadKeys]
  );

  /**
   * The row's switch moved.
   *
   * Enabling is immediate — it is the reversible direction, and the switch is its own undo.
   * Disabling opens the confirm, because it blocks every caller holding the key at once.
   *
   * @param key The key.
   * @param next Where the switch was moved to.
   */
  const handleToggleEnabled = React.useCallback(
    (key: ApiKeyRecord, next: boolean) => {
      if (!next) {
        setOverlayKeyId(key.id);
        setOverlay('disable');
        return;
      }
      setWriteError('');
      void runWrite(key, 'Failed to enable API key', () =>
        setApiKeyEnabled(key.id, true)
      ).then((failure) => {
        // The switch has no dialog of its own on the way *on*, so this one write reports to
        // the page banner rather than to an overlay.
        if (failure) setWriteError(failure);
      });
    },
    [runWrite]
  );

  const handleDisable = React.useCallback(
    (key: ApiKeyRecord) =>
      runWrite(key, 'Failed to disable API key', () => setApiKeyEnabled(key.id, false)),
    [runWrite]
  );

  const handleDelete = React.useCallback(
    (key: ApiKeyRecord) => runWrite(key, 'Failed to delete API key', () => removeApiKey(key.id)),
    [runWrite]
  );

  const handleMcpCreate = React.useCallback(
    async (draft: McpKeyDraft): Promise<string | null> => {
      try {
        const created = await createMcpKey({
          label: draft.label.trim(),
          expires_at: mcpKeyExpiresAt(draft.expiresInDays),
        });
        setSecret({
          value: created.secret,
          summary: describeCreatedMcpKey(draft),
          prefix: displayApiKeyPrefix(created.prefix),
          title: 'MCP key created',
        });
        await loadMcpKeys();
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to create MCP key');
      }
    },
    [loadMcpKeys]
  );

  const handleMcpRevoke = React.useCallback(
    async (key: McpApiKeyMetadata): Promise<string | null> => {
      setBusyRowId(workspaceKeyRowId({ kind: 'mcp', key }));
      try {
        await revokeMcpKey(key.id);
        await loadMcpKeys();
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to revoke MCP key');
      } finally {
        setBusyRowId(null);
      }
    },
    [loadMcpKeys]
  );

  const openRegenerate = React.useCallback((row: WorkspaceKeyRow) => {
    setRegenerateRowId(workspaceKeyRowId(row));
    setOverlay('regenerate');
  }, []);

  /**
   * Replace the confirmed row's secret, then reveal the new one.
   *
   * @returns `null` on success, or the sentence the confirm shows.
   */
  const handleRegenerate = React.useCallback(async (): Promise<string | null> => {
    const row = regenerateRow;
    if (!row) return 'This key is no longer in the list.';
    const kindLabel = WORKSPACE_KEY_KIND_LABEL[row.kind];
    setBusyRowId(workspaceKeyRowId(row));
    try {
      const next =
        row.kind === 'rest'
          ? await regenerateApiKeySecret(row.key.id)
          : await regenerateMcpKey(row.key.id).then((created) => ({
              secret: created.secret,
              keyPrefix: created.prefix,
            }));
      setSecret({
        value: next.secret,
        summary: describeRegeneratedKey(row),
        prefix: displayApiKeyPrefix(next.keyPrefix),
        title: row.kind === 'rest' ? 'API key regenerated' : 'MCP key regenerated',
      });
      await (row.kind === 'rest' ? loadKeys() : loadMcpKeys());
      return null;
    } catch (error) {
      return describeFailure(error, `Failed to regenerate ${kindLabel} key`);
    } finally {
      setBusyRowId(null);
    }
  }, [regenerateRow, loadKeys, loadMcpKeys]);

  const closeOverlay = React.useCallback(() => setOverlay('none'), []);

  // ---- the no-tenant state ---------------------------------------------------------------

  if (!currentTenantId) {
    return (
      <Page>
        <PageHeader
          breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Workspace' }, { label: 'API keys' }]}
          title="API keys"
          description={PAGE_DESCRIPTION}
        />
        <PageBody>
          <div className="akey-gate" data-testid="api-keys-no-tenant">
            <EmptyState
              icon={<Lock aria-hidden />}
              title="No workspace selected"
              description="Please select a workspace before managing API keys."
              action={
                <Button asChild>
                  <a href={TENANTS_ROUTE}>Go to Workspaces</a>
                </Button>
              }
            />
          </div>
        </PageBody>
      </Page>
    );
  }

  const notice = apiKeyExpiryNotice(keys, now);

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: tenantName, href: HOME_ROUTE },
          { label: 'Workspace' },
          { label: 'API keys' },
        ]}
        title="API keys"
        description={PAGE_DESCRIPTION}
        actions={
          <>
            <Button variant="ghost" asChild>
              <a href={API_DOCS_ROUTE} title="REST API reference">
                <BookOpen aria-hidden />
                API docs
              </a>
            </Button>
            {canCreateMcp && (
              <Button variant="outline" data-testid="mcp-keys-create" onClick={openMcpCreate}>
                <Plus aria-hidden />
                Create MCP key
              </Button>
            )}
            <Button kbd="N" data-testid="api-keys-create" onClick={openCreate}>
              <Plus aria-hidden />
              Create API key
            </Button>
          </>
        }
      />

      <PageBody>
        {writeError && (
          <Alert
            variant="error"
            data-testid="api-keys-error"
            onClose={() => setWriteError('')}
            actions={
              <Button variant="outline" size="sm" onClick={() => void loadKeys()}>
                Retry
              </Button>
            }
          >
            {writeError}
          </Alert>
        )}

        {notice && (
          <Alert
            variant={notice.tone}
            data-testid="api-keys-expiry-banner"
            actions={
              <Button variant="outline" size="sm" onClick={openCreate}>
                <KeyRound aria-hidden />
                Create replacement
              </Button>
            }
          >
            <span>
              <strong>{notice.title}</strong> {notice.body}
            </span>
          </Alert>
        )}

        <WorkspaceKeysTable
          rows={rows}
          // Both lists draw together, so MCP rows do not appear under a reader mid-scan.
          loading={loading || (mcpAccess !== 'member' && mcpLoading)}
          error={loadError}
          onRetry={() => void loadKeys()}
          mcpError={mcpAccess === 'member' ? null : mcpLoadError}
          onRetryMcp={() => void loadMcpKeys()}
          mcpNotice={
            mcpAccess === 'member'
              ? 'MCP server keys are managed by workspace administrators — ask one for a key.'
              : null
          }
          busyRowId={busyRowId}
          now={now}
          onToggleEnabled={handleToggleEnabled}
          onDelete={(key) => {
            setOverlayKeyId(key.id);
            setOverlay('delete');
          }}
          onRevoke={(key) => {
            setOverlayMcpKeyId(key.id);
            setOverlay('mcp-revoke');
          }}
          onRegenerate={openRegenerate}
          onCreate={openCreate}
          onCreateMcp={canCreateMcp ? openMcpCreate : undefined}
        />

        <ApiKeyReferenceCards keys={keys} tenantName={tenantName} />
        {mcpAccess !== 'member' && (
          <McpKeyReferenceCard tenantName={tenantName} workspacesHref={TENANTS_ROUTE} />
        )}
      </PageBody>

      <CreateApiKeyDialog
        open={overlay === 'create'}
        onOpenChange={(open) => !open && closeOverlay()}
        onSubmit={handleCreate}
      />

      <ApiKeySecretDialog
        open={secret !== null}
        // The one transition that clears the plaintext key. Nothing else may set it to null,
        // and nothing at all may set it back.
        onOpenChange={(open) => !open && setSecret(null)}
        secret={secret?.value ?? ''}
        summary={secret?.summary ?? ''}
        prefix={secret?.prefix ?? ''}
        title={secret?.title}
      />

      <DisableApiKeyDialog
        open={overlay === 'disable'}
        onOpenChange={(open) => !open && closeOverlay()}
        apiKey={overlayKey}
        onConfirm={handleDisable}
      />

      <DeleteApiKeyDialog
        open={overlay === 'delete'}
        onOpenChange={(open) => !open && closeOverlay()}
        apiKey={overlayKey}
        onConfirm={handleDelete}
      />

      <CreateMcpKeyDialog
        open={overlay === 'mcp-create'}
        onOpenChange={(open) => !open && closeOverlay()}
        onSubmit={handleMcpCreate}
      />

      <RevokeMcpKeyDialog
        open={overlay === 'mcp-revoke'}
        onOpenChange={(open) => !open && closeOverlay()}
        mcpKey={overlayMcpKey}
        onConfirm={handleMcpRevoke}
      />

      <RegenerateKeyDialog
        open={overlay === 'regenerate'}
        onOpenChange={(open) => !open && closeOverlay()}
        target={
          regenerateRow
            ? {
                kind: regenerateRow.kind,
                name: workspaceKeyName(regenerateRow),
                prefix: workspaceKeyPrefix(regenerateRow),
              }
            : null
        }
        onConfirm={handleRegenerate}
      />
    </Page>
  );
}
