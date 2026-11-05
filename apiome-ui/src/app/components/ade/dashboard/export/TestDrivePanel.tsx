'use client';

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { CheckCircle2, CircleSlash, FlaskConical } from 'lucide-react';

import { TAB_LIST_CLASS, tabTriggerClass } from '../../../ui/tabStyles';
import {
  initialTestDriveTab,
  testDriveTabs,
  toolAvailable,
  type ExportTestTool,
  type ExportTestToolKind,
  type TestDriveTab,
} from './exportTestDrive';

/** Draws one tab's body; keyed by tool kind. */
export type TestDriveRenderers = Partial<Record<ExportTestToolKind, (tab: TestDriveTab) => ReactNode>>;

export interface TestDrivePanelProps {
  /** The selected target's `descriptor.test_tools`, straight from the registry. */
  tools: readonly ExportTestTool[] | null | undefined;
  /** The target key (a new target resets the open tab). */
  targetKey: string;
  /** The renderers for the kinds this build can draw; a kind without one gets no tab. */
  renderers: TestDriveRenderers;
}

/**
 * TestDrivePanel — the Review step's **Test drive** tab strip (MFX-44.1, #4367).
 *
 * One tab per tool kind the target's registry entry declares (`descriptor.test_tools`), so a target's
 * tabs appear and disappear with the registry alone, and a new emitter that declares tools needs no
 * UI change. A tab whose tools cannot run on this server is drawn **disabled**, with the server's
 * reason listed under the strip. Full WAI-ARIA tabs: one Tab stop, ←/→/Home/End between the tabs
 * that can open.
 *
 * @param props See {@link TestDrivePanelProps}.
 * @returns The strip and the open tab, or nothing when the target declares no drawable tool.
 */
export function TestDrivePanel({ tools, targetKey, renderers }: TestDrivePanelProps) {
  const drawable = useMemo(() => new Set(Object.keys(renderers)), [renderers]);
  const tabs = useMemo(() => testDriveTabs(tools, drawable), [tools, drawable]);
  const [active, setActive] = useState<ExportTestToolKind | null>(() => initialTestDriveTab(tabs));
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // A different target (or a registry answer that no longer offers the open tab) starts over.
  const activeTab = tabs.find((tab) => tab.kind === active && tab.available) ?? null;
  const signature = `${targetKey}|${tabs.map((tab) => `${tab.kind}:${tab.available}`).join(',')}`;
  useEffect(() => {
    setActive(initialTestDriveTab(tabs));
    // `signature` captures every input that matters; `tabs` changes identity on each registry read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  if (tabs.length === 0) return null;
  const openable = tabs.filter((tab) => tab.available);
  const unavailable = tabs.filter((tab) => !tab.available);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = openable.findIndex((tab) => tab.kind === activeTab?.kind);
    let next: number;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        next = (current + 1) % openable.length;
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        next = (current - 1 + openable.length) % openable.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = openable.length - 1;
        break;
      default:
        return;
    }
    if (openable.length === 0) return;
    event.preventDefault();
    const kind = openable[next].kind;
    setActive(kind);
    tabRefs.current[kind]?.focus();
  };

  return (
    <section className="xstd-panel xstd-testdrive" aria-labelledby="xstd-testdrive-title" data-testid="test-drive-panel">
      <h3 id="xstd-testdrive-title" className="xstd-caps">
        <FlaskConical aria-hidden />
        Test drive
      </h3>
      <div role="tablist" aria-label="Test drive tools" onKeyDown={onKeyDown} className={TAB_LIST_CLASS}>
        {tabs.map((tab) => {
          const selected = tab.kind === activeTab?.kind;
          return (
            <button
              key={tab.kind}
              ref={(node) => {
                tabRefs.current[tab.kind] = node;
              }}
              id={`test-drive-tab-${tab.kind}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={selected ? `test-drive-panel-${tab.kind}` : undefined}
              aria-disabled={!tab.available || undefined}
              tabIndex={selected || (!activeTab && tab === openable[0]) ? 0 : -1}
              title={tab.reason ?? undefined}
              data-testid={`test-drive-tab-${tab.kind}`}
              onClick={() => tab.available && setActive(tab.kind)}
              className={tabTriggerClass({ active: selected, disabled: !tab.available })}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      {unavailable.length > 0 && (
        <ul className="xstd-testdrive__unavailable" data-testid="test-drive-unavailable">
          {unavailable.map((tab) => (
            <li key={tab.kind}>
              <strong>{tab.label}</strong> is unavailable on this server: {tab.reason}
            </li>
          ))}
        </ul>
      )}
      {activeTab && (
        <div
          role="tabpanel"
          id={`test-drive-panel-${activeTab.kind}`}
          aria-labelledby={`test-drive-tab-${activeTab.kind}`}
          tabIndex={0}
          className="xstd-testdrive__body"
          data-testid={`test-drive-body-${activeTab.kind}`}
        >
          {renderers[activeTab.kind]?.(activeTab)}
        </div>
      )}
    </section>
  );
}

/**
 * The toolchain tab's body: each declared check, and whether its tool is installed on this server.
 *
 * @param props The tab's toolchain checks.
 * @returns One row per check.
 */
export function ToolchainChecksList({ tools }: { tools: readonly ExportTestTool[] }) {
  return (
    <ul className="xstd-testdrive__checks" data-testid="toolchain-checks">
      {tools.map((tool) => {
        const ok = toolAvailable(tool);
        return (
          <li key={tool.label} className="xstd-testdrive__check" data-tone={ok ? 'ok' : 'muted'}>
            {ok ? <CheckCircle2 aria-hidden /> : <CircleSlash aria-hidden />}
            <code className="mono">{tool.label}</code>
            <span className="xstd-testdrive__check-status">
              {ok ? 'Installed on this server' : (tool.unavailable_reason ?? 'Not installed on this server.')}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
