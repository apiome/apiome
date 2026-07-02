'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

export interface MigrationTableRow {
  class_schema_id: string;
  class_id: string;
  class_name: string;
  schema: Record<string, unknown>;
}

/** Rule kind: simple expression, script, or SparkSQL. */
export type MigrationRuleType = 'simple' | 'script' | 'sparkSql';

/** A single migration rule: optional name, inputs, rule definition, outputs. Named rules apply transformation; unnamed/passthrough = input→output. */
export interface MigrationRule {
  name?: string;
  inputProperties: string[];
  ruleType: MigrationRuleType;
  ruleContent: string;
  outputProperties: string[];
}

export interface MigrationContextType {
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
  fromVersionId: string | null;
  setFromVersionId: (id: string | null) => void;
  toVersionId: string | null;
  setToVersionId: (id: string | null) => void;
  selectedClassName: string | null;
  setSelectedClassName: (name: string | null) => void;
  fromTables: MigrationTableRow[];
  toTables: MigrationTableRow[];
  setFromTables: (tables: MigrationTableRow[]) => void;
  setToTables: (tables: MigrationTableRow[]) => void;
  /** Rules keyed by edge id (e.g. migration-edge-prop-{propertyName}). */
  migrationRules: Record<string, MigrationRule>;
  setMigrationRules: (rules: Record<string, MigrationRule> | ((prev: Record<string, MigrationRule>) => Record<string, MigrationRule>)) => void;
  /** Increment to trigger sidebar refetch of rule counts (e.g. after saving a rule). */
  incrementRuleCountsVersion: () => void;
  /** Version counter; when it changes, sidebar refetches rule counts. */
  ruleCountsVersion: number;
}

const MigrationContext = createContext<MigrationContextType | undefined>(undefined);

const STORAGE_KEY_PREFIX = 'migration-rules';

function storageKey(projectId: string, fromVersionId: string, toVersionId: string): string {
  return `${STORAGE_KEY_PREFIX}-${projectId}-${fromVersionId}-${toVersionId}`;
}

function loadRulesFromStorage(projectId: string | null, fromId: string | null, toId: string | null): Record<string, MigrationRule> {
  if (!projectId || !fromId || !toId || typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(storageKey(projectId, fromId, toId));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, MigrationRule>;
    return typeof parsed === 'object' && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function saveRulesToStorage(projectId: string | null, fromId: string | null, toId: string | null, rules: Record<string, MigrationRule>) {
  if (!projectId || !fromId || !toId || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey(projectId, fromId, toId), JSON.stringify(rules));
  } catch {
    /* ignore */
  }
}

export function MigrationProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [fromVersionId, setFromVersionId] = useState<string | null>(null);
  const [toVersionId, setToVersionId] = useState<string | null>(null);
  const [selectedClassName, setSelectedClassName] = useState<string | null>(null);
  const [fromTables, setFromTables] = useState<MigrationTableRow[]>([]);
  const [toTables, setToTables] = useState<MigrationTableRow[]>([]);
  const [migrationRules, setMigrationRulesState] = useState<Record<string, MigrationRule>>({});
  const [ruleCountsVersion, setRuleCountsVersion] = useState(0);

  React.useEffect(() => {
    if (!selectedProjectId || !fromVersionId || !toVersionId) {
      setMigrationRulesState({});
      return;
    }
    if (!selectedClassName) {
      setMigrationRulesState({});
      return;
    }
    const params = new URLSearchParams({
      projectId: selectedProjectId,
      fromVersionId,
      toVersionId,
      className: selectedClassName,
    });
    fetch(`/api/migration-plans?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.rules && typeof data.rules === 'object') {
          setMigrationRulesState(data.rules as Record<string, MigrationRule>);
        } else {
          setMigrationRulesState(loadRulesFromStorage(selectedProjectId, fromVersionId, toVersionId));
        }
      })
      .catch(() => {
        setMigrationRulesState(loadRulesFromStorage(selectedProjectId, fromVersionId, toVersionId));
      });
  }, [selectedProjectId, fromVersionId, toVersionId, selectedClassName]);

  const setMigrationRules = React.useCallback(
    (rulesOrUpdater: Record<string, MigrationRule> | ((prev: Record<string, MigrationRule>) => Record<string, MigrationRule>)) => {
      setMigrationRulesState((prev) => {
        const next = typeof rulesOrUpdater === 'function'
          ? (rulesOrUpdater as (p: Record<string, MigrationRule>) => Record<string, MigrationRule>)(prev)
          : rulesOrUpdater;
        saveRulesToStorage(selectedProjectId, fromVersionId, toVersionId, next);
        return next;
      });
    },
    [selectedProjectId, fromVersionId, toVersionId]
  );

  const incrementRuleCountsVersion = React.useCallback(() => {
    setRuleCountsVersion((v) => v + 1);
  }, []);

  return (
    <MigrationContext.Provider
      value={{
        selectedProjectId,
        setSelectedProjectId,
        fromVersionId,
        setFromVersionId,
        toVersionId,
        setToVersionId,
        selectedClassName,
        setSelectedClassName,
        fromTables,
        toTables,
        setFromTables,
        setToTables,
        migrationRules,
        setMigrationRules,
        incrementRuleCountsVersion,
        ruleCountsVersion,
      }}
    >
      {children}
    </MigrationContext.Provider>
  );
}

export function useMigration() {
  const ctx = useContext(MigrationContext);
  if (ctx === undefined) {
    throw new Error('useMigration must be used within MigrationProvider');
  }
  return ctx;
}
