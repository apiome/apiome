'use client';

import * as React from 'react';
import { Ban, Lock, Plus, ShieldAlert, Trash2 } from 'lucide-react';

import { useAuthSession } from '@lib/auth/session-client';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { McpSectionTabs } from '@/app/components/ade/dashboard/mcp/McpSectionTabs';
import { ApiKeySecretDialog } from '@/app/components/ade/apiKeys';
import {
  agentKeyCreateBody,
  createAgentKey,
  createToolset,
  deleteToolset,
  fetchAgentKeys,
  fetchAgentKeyUsage,
  fetchAgentUsage,
  fetchPublishedVersions,
  fetchToolset,
  fetchToolsets,
  revokeAgentKey,
  setToolEnabled,
  toolToggleNeedsConfirmation,
  toolsetLabel,
  updateAgentKeyAllowlist,
  updateToolset,
  versionsWithoutToolset,
  withUpdatedTool,
  AgentAccessError,
  AgentConfirmDialog,
  AgentKeysPanel,
  AgentUsagePanel,
  AllowlistDialog,
  CODE_WRITE_OP_UNCONFIRMED,
  CreateAgentKeyDialog,
  DEFAULT_USAGE_DAYS,
  EnableToolsetDialog,
  ToolsetsPanel,
  type AgentKey,
  type AgentKeyDraft,
  type AgentKeyUsageState,
  type AgentTool,
  type AgentToolsetDetail,
  type AgentToolsetTarget,
  type AgentUsage,
  type PublishedVersionOption,
} from '@/app/components/ade/agentAccess';

/**
 * MCP → Agent access — `/ade/dashboard/mcp/agents` (AGX-3.4, #4540).
 *
 * The Control Panel home for the agent-access APIs, so a tenant can go from a **published
 * version** to a **working agent key with a curated toolset** without leaving the UI:
 *
 * 1. **Toolsets** — *Enable Agent Access* on a published version (AGX-1.2), then switch tools on
 *    and off. Enabling a **write** operation always goes through the confirmation dialog, and the
 *    request carries `confirmWriteOp: true` only from there.
 * 2. **Agent keys** — create a key bound to a toolset with a tool allowlist and optional expiry
 *    (AGX-3.1); its secret is revealed once. Edit the allowlist, revoke, and see today's calls
 *    against the tier's cap (AGX-3.2).
 * 3. **Usage** — calls per day, error rate, latency, calls per tool and top agents from the
 *    AGX-3.3 rollups, over 7 / 30 / 90 days.
 *
 * ### What this page owns
 *
 * The data of all three tabs, every write, and which overlay is open. The panels and dialogs
 * are presentational. Each dialog's write reports its failure back to the dialog; the two
 * immediate writes (a switch flipped without a dialog) report to the page banner.
 *
 * ### The secret's life
 *
 * As on the API keys page: `createAgentKey` resolves with the secret, it goes into {@link secret}
 * for the reveal-once dialog, and closing that dialog is the only transition out.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The MCP section's landing page, the breadcrumb's middle step. */
const MCP_ROUTE = '/ade/dashboard/mcp';

/** Where the reader picks a workspace, for the no-tenant state. */
const TENANTS_ROUTE = '/ade/dashboard/tenants';

/** The three tabs. */
type AgentTab = 'toolsets' | 'keys' | 'usage';

/** Which overlay, if any, is open over the page. */
type Overlay =
  | { kind: 'none' }
  | { kind: 'enable' }
  | { kind: 'create-key'; toolsetId: string | null }
  | { kind: 'allowlist'; keyId: string }
  | { kind: 'revoke'; keyId: string }
  | { kind: 'delete-toolset'; toolset: AgentToolsetDetail }
  | { kind: 'confirm-write'; toolset: AgentToolsetDetail; tool: AgentTool };

/**
 * Turn a caught failure into the sentence to show.
 *
 * @param error - Whatever was caught.
 * @param fallback - What to say when it carried no message.
 * @returns The sentence.
 */
function describeFailure(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * The Agent access page.
 *
 * @returns The header, the MCP section tabs, the three panels and their overlays.
 */
export default function AgentAccessClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;

  const [tab, setTab] = React.useState<AgentTab>('toolsets');
  const [overlay, setOverlay] = React.useState<Overlay>({ kind: 'none' });
  /** A failed immediate write (a switch with no dialog), shown above the tabs. */
  const [pageError, setPageError] = React.useState('');

  // ---- published versions (for names and the "Enable" picker) ----------------------------
  const [versions, setVersions] = React.useState<PublishedVersionOption[]>([]);

  // ---- toolsets ------------------------------------------------------------------------------
  const [toolsets, setToolsets] = React.useState<AgentToolsetDetail[]>([]);
  const [toolsetsLoading, setToolsetsLoading] = React.useState(true);
  const [toolsetsError, setToolsetsError] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<AgentToolsetDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState<string | null>(null);
  const [busyToolId, setBusyToolId] = React.useState<string | null>(null);
  const [settingsBusy, setSettingsBusy] = React.useState(false);

  // ---- keys ----------------------------------------------------------------------------------
  const [keys, setKeys] = React.useState<AgentKey[]>([]);
  const [keysLoading, setKeysLoading] = React.useState(true);
  const [keysError, setKeysError] = React.useState<string | null>(null);
  const [includeRevoked, setIncludeRevoked] = React.useState(false);
  const [keyUsage, setKeyUsage] = React.useState<Record<string, AgentKeyUsageState>>({});

  // ---- usage ---------------------------------------------------------------------------------
  const [usage, setUsage] = React.useState<AgentUsage | null>(null);
  const [usageLoading, setUsageLoading] = React.useState(false);
  const [usageError, setUsageError] = React.useState<string | null>(null);
  const [days, setDays] = React.useState(DEFAULT_USAGE_DAYS);

  /** The new key's secret, for exactly as long as its dialog is open. */
  const [secret, setSecret] = React.useState<{ value: string; summary: string; prefix: string } | null>(
    null
  );

  // ---- loads ---------------------------------------------------------------------------------

  const loadVersions = React.useCallback(async () => {
    if (!tenantId) return;
    try {
      setVersions(await fetchPublishedVersions(tenantId));
    } catch {
      // Names fall back to the version label, and the Enable dialog explains it has nothing to
      // offer; neither is worth failing the page for.
      setVersions([]);
    }
  }, [tenantId]);

  const loadToolsets = React.useCallback(async () => {
    if (!tenantId) return;
    setToolsetsLoading(true);
    setToolsetsError(null);
    try {
      const list = await fetchToolsets();
      setToolsets(list);
      setSelectedId((current) =>
        current && list.some((t) => t.id === current) ? current : (list[0]?.id ?? null)
      );
    } catch (error) {
      setToolsets([]);
      setToolsetsError(describeFailure(error, 'Failed to load toolsets'));
    } finally {
      setToolsetsLoading(false);
    }
  }, [tenantId]);

  const loadDetail = React.useCallback(async (toolsetId: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      setDetail(await fetchToolset(toolsetId));
    } catch (error) {
      setDetail(null);
      setDetailError(describeFailure(error, 'Failed to load the toolset'));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const loadKeys = React.useCallback(async () => {
    if (!tenantId) return;
    setKeysLoading(true);
    setKeysError(null);
    try {
      const list = await fetchAgentKeys(includeRevoked);
      setKeys(list);
      // Usage is per key and secondary: each row fills in on its own, and a failure marks only
      // that row.
      setKeyUsage({});
      list.forEach((key) => {
        fetchAgentKeyUsage(key.id)
          .then((u) => setKeyUsage((current) => ({ ...current, [key.id]: u })))
          .catch(() => setKeyUsage((current) => ({ ...current, [key.id]: 'error' })));
      });
    } catch (error) {
      setKeys([]);
      setKeysError(describeFailure(error, 'Failed to load agent keys'));
    } finally {
      setKeysLoading(false);
    }
  }, [tenantId, includeRevoked]);

  const loadUsage = React.useCallback(async () => {
    if (!tenantId) return;
    setUsageLoading(true);
    setUsageError(null);
    try {
      setUsage(await fetchAgentUsage(days));
    } catch (error) {
      setUsageError(describeFailure(error, 'Failed to load usage'));
    } finally {
      setUsageLoading(false);
    }
  }, [tenantId, days]);

  React.useEffect(() => {
    void loadVersions();
    void loadToolsets();
  }, [loadVersions, loadToolsets]);

  React.useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  // Usage is loaded when its tab is first shown, and again when the period changes.
  React.useEffect(() => {
    if (tab === 'usage') void loadUsage();
  }, [tab, loadUsage]);

  React.useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  // ---- toolset writes ------------------------------------------------------------------------

  // The list's cards show each toolset's on/off, target and counts. Whenever the detail changes
  // (a switch, a setting), its card is brought in line, so the two can never disagree.
  React.useEffect(() => {
    if (!detail) return;
    setToolsets((list) =>
      list.map((t) => (t.id === detail.id ? { ...t, ...detail, tools: [] } : t))
    );
  }, [detail]);

  const handleEnable = React.useCallback(
    async (versionId: string, target: AgentToolsetTarget): Promise<string | null> => {
      try {
        const created = await createToolset(versionId, target);
        await loadToolsets();
        setSelectedId(created.id);
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to enable Agent Access');
      }
    },
    [loadToolsets]
  );

  const handleToolsetSettings = React.useCallback(
    async (toolset: AgentToolsetDetail, patch: { enabled?: boolean; target?: AgentToolsetTarget }) => {
      setSettingsBusy(true);
      setPageError('');
      try {
        const updated = await updateToolset(toolset.id, patch);
        setDetail((current) =>
          current && current.id === toolset.id
            ? { ...current, ...updated, tools: current.tools }
            : current
        );
      } catch (error) {
        setPageError(describeFailure(error, 'Failed to update the toolset'));
      } finally {
        setSettingsBusy(false);
      }
    },
    []
  );

  /**
   * Write one tool's switch.
   *
   * @param toolset - The toolset.
   * @param tool - The tool.
   * @param enabled - The new state.
   * @param confirmWriteOp - Whether the write-op confirmation was given.
   * @returns `null` on success, or the message to show.
   */
  const writeTool = React.useCallback(
    async (
      toolset: AgentToolsetDetail,
      tool: AgentTool,
      enabled: boolean,
      confirmWriteOp: boolean
    ): Promise<string | null> => {
      setBusyToolId(tool.id);
      try {
        const updated = await setToolEnabled(toolset.id, tool.id, enabled, confirmWriteOp);
        setDetail((current) =>
          current && current.id === toolset.id ? withUpdatedTool(current, updated) : current
        );
        return null;
      } catch (error) {
        // The server is the judge of what is a write op. If it asks for a confirmation the
        // switch did not know was needed, ask for it rather than reporting a failure.
        if (error instanceof AgentAccessError && error.code === CODE_WRITE_OP_UNCONFIRMED) {
          setOverlay({ kind: 'confirm-write', toolset, tool: { ...tool, writeOp: true } });
          return null;
        }
        return describeFailure(error, 'Failed to update the tool');
      } finally {
        setBusyToolId(null);
      }
    },
    []
  );

  const handleToggleTool = React.useCallback(
    (toolset: AgentToolsetDetail, tool: AgentTool, enabled: boolean) => {
      if (toolToggleNeedsConfirmation(tool, enabled)) {
        setOverlay({ kind: 'confirm-write', toolset, tool });
        return;
      }
      setPageError('');
      void writeTool(toolset, tool, enabled, false).then((failure) => {
        if (failure) setPageError(failure);
      });
    },
    [writeTool]
  );

  const handleDeleteToolset = React.useCallback(
    async (toolset: AgentToolsetDetail): Promise<string | null> => {
      try {
        await deleteToolset(toolset.id);
        await Promise.all([loadToolsets(), loadKeys()]);
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to delete the toolset');
      }
    },
    [loadKeys, loadToolsets]
  );

  // ---- key writes ----------------------------------------------------------------------------

  const handleCreateKey = React.useCallback(
    async (draft: AgentKeyDraft): Promise<string | null> => {
      try {
        const { key, secret: value } = await createAgentKey(agentKeyCreateBody(draft, new Date()));
        const toolset = toolsets.find((t) => t.id === key.toolsetId);
        setSecret({
          value,
          prefix: key.keyPrefix,
          summary: `${key.name} · ${toolset ? toolsetLabel(toolset, versions) : 'toolset'} · ${
            key.toolAllowlist.length
          } tool${key.toolAllowlist.length === 1 ? '' : 's'}${
            key.expiresAt ? ` · expires ${new Date(key.expiresAt).toLocaleDateString('en-US')}` : ''
          }`,
        });
        setTab('keys');
        await loadKeys();
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to create the agent key');
      }
    },
    [loadKeys, toolsets, versions]
  );

  const handleAllowlist = React.useCallback(
    async (key: AgentKey, toolAllowlist: string[]): Promise<string | null> => {
      try {
        const updated = await updateAgentKeyAllowlist(key.id, toolAllowlist);
        setKeys((list) => list.map((k) => (k.id === updated.id ? updated : k)));
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to save the allowlist');
      }
    },
    []
  );

  const handleRevoke = React.useCallback(
    async (key: AgentKey): Promise<string | null> => {
      try {
        await revokeAgentKey(key.id);
        await loadKeys();
        return null;
      } catch (error) {
        return describeFailure(error, 'Failed to revoke the agent key');
      }
    },
    [loadKeys]
  );

  const closeOverlay = React.useCallback(() => setOverlay({ kind: 'none' }), []);
  const openEnable = React.useCallback(() => setOverlay({ kind: 'enable' }), []);
  const openCreateKey = React.useCallback(
    (toolsetId: string | null) => setOverlay({ kind: 'create-key', toolsetId }),
    []
  );

  const overlayKey =
    overlay.kind === 'allowlist' || overlay.kind === 'revoke'
      ? (keys.find((k) => k.id === overlay.keyId) ?? null)
      : null;

  // ---- the no-tenant state -------------------------------------------------------------------

  const breadcrumb = [
    { label: 'Home', href: HOME_ROUTE },
    { label: 'MCP servers', href: MCP_ROUTE },
    { label: 'Agent access' },
  ];
  const description =
    'Curate which published operations AI agents may call, mint agent keys, and see what agents do.';

  if (!tenantId) {
    return (
      <Page>
        <PageHeader breadcrumb={breadcrumb} title="Agent access" description={description} />
        <PageBody>
          <EmptyState
            icon={<Lock aria-hidden />}
            title="No workspace selected"
            description="Please select a workspace before managing agent access."
            action={
              <Button asChild>
                <a href={TENANTS_ROUTE}>Go to Workspaces</a>
              </Button>
            }
            data-testid="agx-no-tenant"
          />
        </PageBody>
      </Page>
    );
  }

  const enableChoices = versionsWithoutToolset(versions, toolsets);
  const activeKeyCount = keys.filter((k) => k.status !== 'revoked').length;

  return (
    <Page>
      <PageHeader
        breadcrumb={breadcrumb}
        title="Agent access"
        description={description}
        actions={
          <Button onClick={openEnable} data-testid="agx-enable">
            <Plus aria-hidden />
            Enable Agent Access
          </Button>
        }
      />

      <PageBody>
        <McpSectionTabs />

        {pageError && (
          <Alert variant="error" data-testid="agx-page-error" onClose={() => setPageError('')}>
            {pageError}
          </Alert>
        )}

        <Tabs value={tab} onValueChange={(value) => setTab(value as AgentTab)} className="agx-tabs">
          <TabsList aria-label="Agent access">
            <TabsTrigger value="toolsets" data-testid="agx-tab-toolsets">
              Toolsets
              <TabsCount>{toolsets.length}</TabsCount>
            </TabsTrigger>
            <TabsTrigger value="keys" data-testid="agx-tab-keys">
              Agent keys
              <TabsCount>{activeKeyCount}</TabsCount>
            </TabsTrigger>
            <TabsTrigger value="usage" data-testid="agx-tab-usage">
              Usage
            </TabsTrigger>
          </TabsList>

          <TabsContent value="toolsets">
            <ToolsetsPanel
              toolsets={toolsets}
              versions={versions}
              loading={toolsetsLoading}
              error={toolsetsError}
              onRetry={() => {
                void loadToolsets();
                if (selectedId) void loadDetail(selectedId);
              }}
              selectedId={selectedId}
              onSelect={setSelectedId}
              detail={detail}
              detailLoading={detailLoading}
              detailError={detailError}
              busyToolId={busyToolId}
              settingsBusy={settingsBusy}
              onEnable={openEnable}
              onToggleToolset={(toolset, enabled) => void handleToolsetSettings(toolset, { enabled })}
              onChangeTarget={(toolset, target) => void handleToolsetSettings(toolset, { target })}
              onDelete={(toolset) => setOverlay({ kind: 'delete-toolset', toolset })}
              onToggleTool={handleToggleTool}
              onCreateKey={(toolset) => openCreateKey(toolset.id)}
            />
          </TabsContent>

          <TabsContent value="keys">
            <AgentKeysPanel
              keys={keys}
              toolsets={toolsets}
              versions={versions}
              usage={keyUsage}
              loading={keysLoading}
              error={keysError}
              onRetry={() => void loadKeys()}
              includeRevoked={includeRevoked}
              onIncludeRevokedChange={setIncludeRevoked}
              onCreate={() => openCreateKey(null)}
              onEditAllowlist={(key) => setOverlay({ kind: 'allowlist', keyId: key.id })}
              onRevoke={(key) => setOverlay({ kind: 'revoke', keyId: key.id })}
            />
          </TabsContent>

          <TabsContent value="usage">
            <AgentUsagePanel
              usage={usage}
              loading={usageLoading}
              error={usageError}
              onRetry={() => void loadUsage()}
              days={days}
              onDaysChange={setDays}
            />
          </TabsContent>
        </Tabs>
      </PageBody>

      <EnableToolsetDialog
        open={overlay.kind === 'enable'}
        onOpenChange={(open) => !open && closeOverlay()}
        versions={enableChoices}
        onSubmit={handleEnable}
      />

      <CreateAgentKeyDialog
        open={overlay.kind === 'create-key'}
        onOpenChange={(open) => !open && closeOverlay()}
        toolsets={toolsets}
        versions={versions}
        initialToolsetId={overlay.kind === 'create-key' ? overlay.toolsetId : null}
        loadToolset={fetchToolset}
        onSubmit={handleCreateKey}
      />

      <AllowlistDialog
        open={overlay.kind === 'allowlist'}
        onOpenChange={(open) => !open && closeOverlay()}
        agentKey={overlayKey}
        loadToolset={fetchToolset}
        onSubmit={handleAllowlist}
      />

      <AgentConfirmDialog
        open={overlay.kind === 'confirm-write'}
        onOpenChange={(open) => !open && closeOverlay()}
        tone="warn"
        icon={<ShieldAlert aria-hidden />}
        title="Let agents call a write operation?"
        description={
          overlay.kind === 'confirm-write' ? (
            <>
              <code className="mono">{overlay.tool.toolName}</code> ({overlay.tool.operation}) can
              change data in {overlay.toolset.target === 'mock' ? 'the mock' : 'production'}.
            </>
          ) : (
            ''
          )
        }
        confirmLabel="Enable write operation"
        busyLabel="Enabling…"
        onConfirm={() =>
          overlay.kind === 'confirm-write'
            ? writeTool(overlay.toolset, overlay.tool, true, true)
            : Promise.resolve(null)
        }
        testId="agx-write-confirm"
      >
        <ul className="agx-consequences">
          <li>Any agent key whose allowlist names this tool can call it on its next request.</li>
          <li>Your confirmation is recorded with your name and the time, and audited.</li>
          <li>Turning the tool off clears the confirmation; turning it on again asks again.</li>
        </ul>
      </AgentConfirmDialog>

      <AgentConfirmDialog
        open={overlay.kind === 'delete-toolset'}
        onOpenChange={(open) => !open && closeOverlay()}
        tone="danger"
        icon={<Trash2 aria-hidden />}
        title="Delete this toolset?"
        description={
          overlay.kind === 'delete-toolset'
            ? `Agent Access for ${toolsetLabel(overlay.toolset, versions)} is removed.`
            : ''
        }
        confirmLabel="Delete toolset"
        busyLabel="Deleting…"
        onConfirm={() =>
          overlay.kind === 'delete-toolset'
            ? handleDeleteToolset(overlay.toolset)
            : Promise.resolve(null)
        }
        testId="agx-delete-toolset"
      >
        <Alert variant="danger">
          Its agent keys and upstream credentials are deleted with it. Agents holding those keys
          are refused on their next request.
        </Alert>
      </AgentConfirmDialog>

      <AgentConfirmDialog
        open={overlay.kind === 'revoke'}
        onOpenChange={(open) => !open && closeOverlay()}
        tone="danger"
        icon={<Ban aria-hidden />}
        title="Revoke this agent key?"
        description={
          overlayKey ? (
            <>
              <strong>{overlayKey.name}</strong> (<code className="mono">{overlayKey.keyPrefix}</code>)
              stops working on the agent&apos;s next request. This cannot be undone.
            </>
          ) : (
            ''
          )
        }
        confirmLabel="Revoke key"
        busyLabel="Revoking…"
        onConfirm={() => (overlayKey ? handleRevoke(overlayKey) : Promise.resolve(null))}
        testId="agx-revoke"
      />

      <ApiKeySecretDialog
        open={secret !== null}
        // The one transition that clears the secret; nothing sets it back.
        onOpenChange={(open) => !open && setSecret(null)}
        title="Agent key created"
        secret={secret?.value ?? ''}
        summary={secret?.summary ?? ''}
        prefix={secret?.prefix ?? ''}
      />
    </Page>
  );
}
