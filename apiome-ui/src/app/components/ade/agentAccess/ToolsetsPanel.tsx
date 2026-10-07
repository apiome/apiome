'use client';

import * as React from 'react';
import { Bot, KeyRound, Plus, ShieldAlert, Trash2 } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Switch } from '@/app/components/ui/Switch';

import {
  toolsetLabel,
  type AgentTool,
  type AgentToolset,
  type AgentToolsetDetail,
  type AgentToolsetTarget,
  type PublishedVersionOption,
} from './agentAccessModel';

/**
 * The toolset editor — AGX-3.4 (#4540), over AGX-1.2's toolsets.
 *
 * Left: the tenant's toolsets, one per published version with Agent Access. Right: the chosen
 * one's settings (on/off, production or mock) and its tools, each with a switch.
 *
 * The component is presentational: the page owns the data and every write. The one rule it
 * carries is **how a write op is shown** — with a `Write` badge on its row, and with the count of
 * exposed writes on the toolset's card, so a toolset that lets agents change data never looks
 * like one that only reads.
 */

/** Props for {@link ToolsetsPanel}. */
export interface ToolsetsPanelProps {
  toolsets: readonly AgentToolset[];
  versions: readonly PublishedVersionOption[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** The toolset whose detail is shown. */
  selectedId: string | null;
  onSelect: (toolsetId: string) => void;
  /** The selected toolset with its tools, once loaded. */
  detail: AgentToolsetDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  /** A tool or setting write in flight, so only its control goes inert. */
  busyToolId: string | null;
  settingsBusy: boolean;
  /** Open "Enable Agent Access". */
  onEnable: () => void;
  onToggleToolset: (toolset: AgentToolsetDetail, enabled: boolean) => void;
  onChangeTarget: (toolset: AgentToolsetDetail, target: AgentToolsetTarget) => void;
  onDelete: (toolset: AgentToolsetDetail) => void;
  onToggleTool: (toolset: AgentToolsetDetail, tool: AgentTool, enabled: boolean) => void;
  /** Open "Create agent key" for this toolset. */
  onCreateKey: (toolset: AgentToolsetDetail) => void;
}

/**
 * The editor.
 *
 * @param props See {@link ToolsetsPanelProps}.
 * @returns The toolset list and the selected toolset's detail.
 */
export default function ToolsetsPanel(props: ToolsetsPanelProps) {
  const { toolsets, versions, loading, error, onRetry, selectedId, onSelect, onEnable } = props;

  if (loading && toolsets.length === 0) {
    return <LoadingState message="Loading toolsets…" data-testid="agx-toolsets-loading" />;
  }
  if (error) {
    return (
      <ErrorState
        title="Toolsets could not be loaded"
        description={error}
        onRetry={onRetry}
        data-testid="agx-toolsets-error"
      />
    );
  }
  if (toolsets.length === 0) {
    return (
      <EmptyState
        icon={<Bot aria-hidden />}
        title="No version has Agent Access yet"
        description="Pick a published version to expose its operations to agents as MCP tools."
        action={
          <Button onClick={onEnable} data-testid="agx-toolsets-empty-enable">
            <Plus aria-hidden />
            Enable Agent Access
          </Button>
        }
        data-testid="agx-toolsets-empty"
      />
    );
  }

  return (
    <div className="agx-toolsets" data-testid="agx-toolsets">
      <ul className="agx-toolset-list" aria-label="Toolsets">
        {toolsets.map((toolset) => {
          const selected = toolset.id === selectedId;
          return (
            <li key={toolset.id}>
              <button
                type="button"
                className="agx-toolset-card"
                data-selected={selected || undefined}
                aria-current={selected ? 'true' : undefined}
                data-testid={`agx-toolset-${toolset.id}`}
                onClick={() => onSelect(toolset.id)}
              >
                <span className="agx-toolset-card__name">{toolsetLabel(toolset, versions)}</span>
                <span className="agx-toolset-card__meta">
                  {toolset.enabled ? (
                    <Badge status="active">On</Badge>
                  ) : (
                    <Badge status="disabled">Off</Badge>
                  )}
                  <Badge variant="neutral">{toolset.target === 'mock' ? 'Mock' : 'Production'}</Badge>
                  <span>
                    {toolset.enabledToolCount} of {toolset.toolCount} tools
                  </span>
                  {toolset.enabledWriteOpCount > 0 && (
                    <Badge status="warn">
                      {toolset.enabledWriteOpCount} write{toolset.enabledWriteOpCount === 1 ? '' : 's'}
                    </Badge>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <ToolsetDetail {...props} />
    </div>
  );
}

/**
 * The selected toolset's settings and tools.
 *
 * @param props The panel's props.
 * @returns The detail card, or its loading / error state.
 */
function ToolsetDetail({
  versions,
  detail,
  detailLoading,
  detailError,
  busyToolId,
  settingsBusy,
  onToggleToolset,
  onChangeTarget,
  onDelete,
  onToggleTool,
  onCreateKey,
  onRetry,
}: ToolsetsPanelProps) {
  if (detailError) {
    return (
      <ErrorState
        title="This toolset could not be loaded"
        description={detailError}
        onRetry={onRetry}
        data-testid="agx-toolset-detail-error"
      />
    );
  }
  if (!detail || detailLoading) {
    return <LoadingState message="Loading tools…" data-testid="agx-toolset-detail-loading" />;
  }

  const switchId = `agx-toolset-enabled-${detail.id}`;

  return (
    <section className="agx-toolset-detail" aria-label="Toolset" data-testid="agx-toolset-detail">
      <header className="agx-toolset-detail__head">
        <h3 className="agx-section-title">{toolsetLabel(detail, versions)}</h3>
        <div className="agx-toolset-detail__actions">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onCreateKey(detail)}
            data-testid="agx-toolset-create-key"
          >
            <KeyRound aria-hidden />
            Create agent key
          </Button>
          <Button
            variant="danger-soft"
            size="sm"
            disabled={settingsBusy}
            onClick={() => onDelete(detail)}
            data-testid="agx-toolset-delete"
          >
            <Trash2 aria-hidden />
            Delete
          </Button>
        </div>
      </header>

      <div className="agx-toolset-settings">
        <div className="agx-inline-field">
          <Switch
            id={switchId}
            checked={detail.enabled}
            disabled={settingsBusy}
            onCheckedChange={(checked) => onToggleToolset(detail, checked)}
            data-testid="agx-toolset-enabled"
          />
          <Label htmlFor={switchId}>Agent Access {detail.enabled ? 'on' : 'off'}</Label>
        </div>
        <div className="agx-inline-field">
          <span className="agx-legend" id={`${switchId}-target`}>
            Calls go to
          </span>
          <Segmented
            aria-labelledby={`${switchId}-target`}
            value={detail.target}
            size="sm"
            onValueChange={(value) => {
              const next: AgentToolsetTarget = value === 'mock' ? 'mock' : 'prod';
              if (next !== detail.target) onChangeTarget(detail, next);
            }}
            data-testid="agx-toolset-target"
          >
            <SegmentedItem value="prod" disabled={settingsBusy}>
              Production
            </SegmentedItem>
            <SegmentedItem value="mock" disabled={settingsBusy}>
              Mock
            </SegmentedItem>
          </Segmented>
        </div>
      </div>

      {!detail.enabled && (
        <p className="agx-hint" data-testid="agx-toolset-off-note">
          Agent Access is off: agents see none of these tools, whatever their switches say.
        </p>
      )}

      {detail.tools.length === 0 ? (
        <EmptyState
          variant="compact"
          title="No callable operations"
          description="This version has no operations that can be exposed as tools."
        />
      ) : (
        <div className="agx-table-wrap">
          <table className="agx-table" data-testid="agx-tools-table">
            <caption className="sr-only">Tools of this toolset</caption>
            <thead>
              <tr>
                <th scope="col">Exposed</th>
                <th scope="col">Tool</th>
                <th scope="col">Operation</th>
                <th scope="col">Kind</th>
              </tr>
            </thead>
            <tbody>
              {detail.tools.map((tool) => {
                const id = `agx-tool-${tool.id}`;
                return (
                  <tr key={tool.id} data-testid={`agx-tool-row-${tool.toolName}`}>
                    <td>
                      <Switch
                        id={id}
                        checked={tool.enabled}
                        disabled={busyToolId === tool.id}
                        aria-label={`Expose ${tool.toolName}`}
                        onCheckedChange={(checked) => onToggleTool(detail, tool, checked)}
                        data-testid={`agx-tool-switch-${tool.toolName}`}
                      />
                    </td>
                    <td>
                      <label htmlFor={id} className="agx-cell-mono mono">
                        {tool.toolName}
                      </label>
                    </td>
                    <td className="agx-cell-mono mono">{tool.operation}</td>
                    <td>
                      {tool.writeOp ? (
                        <Badge status="warn" title="Can change data upstream">
                          <ShieldAlert aria-hidden />
                          Write
                        </Badge>
                      ) : (
                        <Badge variant="neutral">Read</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
