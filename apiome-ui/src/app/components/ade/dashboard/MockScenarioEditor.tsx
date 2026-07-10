'use client';

/**
 * Mock scenario override editor (#4454, SIM-4.2).
 *
 * Dialog for authoring named mock scenarios ("happy path", "quota exceeded", ...)
 * on one version. Each scenario maps operations ("METHOD /path/{template}") to
 * canned responses (status + headers + body); two or more responses on one
 * operation form a per-call sequence. Definitions persist in the version's
 * `mock_settings` and are served by apiome-mock when a consumer sends the
 * `X-Mock-Scenario: <name>` header.
 *
 * Round-trips through `/api/versions/{id}/mock/scenarios` (GET on open, PUT on
 * save). Server-side validation failures (HTTP 422 from REST) are listed
 * verbatim under the form; a response can opt out of spec conformance with the
 * "Off-spec" flag for deliberately broken responses.
 */

import { useCallback, useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Textarea } from '../../ui/Textarea';

/** One canned response as stored by REST (camelCase wire shape). */
export interface MockScenarioResponsePayload {
  status: number;
  headers?: Record<string, string>;
  body?: unknown;
  mediaType?: string;
  offSpec?: boolean;
}

/** Scenario definitions as stored by REST, keyed by scenario name. */
export type MockScenariosPayload = Record<
  string,
  {
    description?: string;
    operations: Record<string, { responses: MockScenarioResponsePayload[] }>;
  }
>;

/** Form state for one canned response (text fields until save). */
interface ResponseDraft {
  status: string;
  headersText: string;
  bodyText: string;
  mediaType: string;
  offSpec: boolean;
}

/** Form state for one operation override. */
interface OperationDraft {
  key: string;
  responses: ResponseDraft[];
}

/** Form state for one scenario. */
interface ScenarioDraft {
  name: string;
  description: string;
  operations: OperationDraft[];
}

export interface MockScenarioEditorProps {
  /** Version record id (the `versions.id` UUID, not the semver label). */
  versionRecordId: string;
  /** Project the version belongs to (forwarded to the proxy routes). */
  projectId: string;
  /** Human version label (e.g. `1.2.0`), used in the dialog title. */
  versionLabel: string;
  /** Whether the dialog is open (controlled). */
  open: boolean;
  /** Called when the dialog wants to open/close. */
  onOpenChange: (open: boolean) => void;
}

const EMPTY_RESPONSE: ResponseDraft = {
  status: '200',
  headersText: '',
  bodyText: '',
  mediaType: '',
  offSpec: false,
};

/** Convert the stored wire shape into editable drafts. */
function draftsFromPayload(payload: MockScenariosPayload): ScenarioDraft[] {
  return Object.entries(payload).map(([name, scenario]) => ({
    name,
    description: scenario.description ?? '',
    operations: Object.entries(scenario.operations ?? {}).map(([key, override]) => ({
      key,
      responses: (override.responses ?? []).map((response) => ({
        status: String(response.status),
        headersText:
          response.headers && Object.keys(response.headers).length > 0
            ? JSON.stringify(response.headers, null, 2)
            : '',
        bodyText: 'body' in response ? JSON.stringify(response.body, null, 2) : '',
        mediaType: response.mediaType ?? '',
        offSpec: Boolean(response.offSpec),
      })),
    })),
  }));
}

/**
 * Convert drafts back into the wire shape.
 *
 * @returns the payload, or a list of client-side errors when a field cannot
 * be parsed (invalid JSON, non-numeric status, blank names).
 */
function payloadFromDrafts(
  drafts: ScenarioDraft[]
): { payload: MockScenariosPayload; errors: string[] } {
  const payload: MockScenariosPayload = {};
  const errors: string[] = [];

  drafts.forEach((scenario, scenarioIndex) => {
    const name = scenario.name.trim();
    const label = name || `scenario ${scenarioIndex + 1}`;
    if (!name) {
      errors.push(`Scenario ${scenarioIndex + 1}: name is required.`);
      return;
    }
    if (payload[name]) {
      errors.push(`Scenario '${name}': duplicate scenario name.`);
      return;
    }

    const operations: Record<string, { responses: MockScenarioResponsePayload[] }> = {};
    scenario.operations.forEach((operation, operationIndex) => {
      const key = operation.key.trim();
      if (!key) {
        errors.push(`Scenario '${label}': operation ${operationIndex + 1} needs a key like 'GET /pets'.`);
        return;
      }
      if (operations[key]) {
        errors.push(`Scenario '${label}': duplicate operation '${key}'.`);
        return;
      }

      const responses: MockScenarioResponsePayload[] = [];
      operation.responses.forEach((response, responseIndex) => {
        const context = `Scenario '${label}', operation '${key}', response ${responseIndex + 1}`;
        const status = Number.parseInt(response.status, 10);
        if (!Number.isFinite(status) || status < 100 || status > 599) {
          errors.push(`${context}: status must be a number between 100 and 599.`);
          return;
        }
        const entry: MockScenarioResponsePayload = { status };

        if (response.headersText.trim()) {
          try {
            const headers: unknown = JSON.parse(response.headersText);
            if (!headers || typeof headers !== 'object' || Array.isArray(headers)) {
              throw new Error('not an object');
            }
            entry.headers = Object.fromEntries(
              Object.entries(headers as Record<string, unknown>).map(([k, v]) => [k, String(v)])
            );
          } catch {
            errors.push(`${context}: headers must be a JSON object of string values.`);
            return;
          }
        }

        if (response.bodyText.trim()) {
          try {
            entry.body = JSON.parse(response.bodyText);
          } catch {
            errors.push(`${context}: body must be valid JSON (leave blank for an empty body).`);
            return;
          }
        }

        if (response.mediaType.trim()) {
          entry.mediaType = response.mediaType.trim();
        }
        if (response.offSpec) {
          entry.offSpec = true;
        }
        responses.push(entry);
      });

      if (responses.length > 0) {
        operations[key] = { responses };
      } else {
        errors.push(`Scenario '${label}': operation '${key}' needs at least one response.`);
      }
    });

    payload[name] = {
      ...(scenario.description.trim() ? { description: scenario.description.trim() } : {}),
      operations,
    };
  });

  return { payload, errors };
}

/**
 * Render the scenario editor dialog for one version.
 *
 * @param props - see {@link MockScenarioEditorProps}
 * @returns the controlled dialog element
 */
export function MockScenarioEditor({
  versionRecordId,
  projectId,
  versionLabel,
  open,
  onOpenChange,
}: MockScenarioEditorProps) {
  const [drafts, setDrafts] = useState<ScenarioDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  /** Load persisted definitions every time the dialog opens. */
  const load = useCallback(async () => {
    setLoading(true);
    setErrors([]);
    try {
      const response = await fetch(
        `/api/versions/${versionRecordId}/mock/scenarios?projectId=${encodeURIComponent(projectId)}`
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload?.success) {
        toast.error(payload?.error || `Failed to load scenarios for v${versionLabel}.`);
        return;
      }
      setDrafts(draftsFromPayload((payload.scenarios ?? {}) as MockScenariosPayload));
    } catch (error) {
      console.error('Failed to load mock scenarios:', error);
      toast.error(`Failed to load scenarios for v${versionLabel}.`);
    } finally {
      setLoading(false);
    }
  }, [versionRecordId, projectId, versionLabel]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  /** Validate drafts client-side, then PUT the full definition set. */
  const handleSave = async () => {
    if (saving) return;
    const { payload, errors: clientErrors } = payloadFromDrafts(drafts);
    if (clientErrors.length > 0) {
      setErrors(clientErrors);
      return;
    }

    setSaving(true);
    setErrors([]);
    try {
      const response = await fetch(`/api/versions/${versionRecordId}/mock/scenarios`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId, scenarios: payload }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.success) {
        if (Array.isArray(result?.errors) && result.errors.length > 0) {
          setErrors(result.errors as string[]);
        } else {
          toast.error(result?.error || `Failed to save scenarios for v${versionLabel}.`);
        }
        return;
      }
      toast.success(`Scenarios saved for v${versionLabel}.`);
      onOpenChange(false);
    } catch (error) {
      console.error('Failed to save mock scenarios:', error);
      toast.error(`Failed to save scenarios for v${versionLabel}.`);
    } finally {
      setSaving(false);
    }
  };

  const updateScenario = (index: number, patch: Partial<ScenarioDraft>) => {
    setDrafts((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const updateOperation = (scenarioIndex: number, operationIndex: number, patch: Partial<OperationDraft>) => {
    setDrafts((prev) =>
      prev.map((s, i) =>
        i === scenarioIndex
          ? {
              ...s,
              operations: s.operations.map((o, j) => (j === operationIndex ? { ...o, ...patch } : o)),
            }
          : s
      )
    );
  };

  const updateResponse = (
    scenarioIndex: number,
    operationIndex: number,
    responseIndex: number,
    patch: Partial<ResponseDraft>
  ) => {
    setDrafts((prev) =>
      prev.map((s, i) =>
        i === scenarioIndex
          ? {
              ...s,
              operations: s.operations.map((o, j) =>
                j === operationIndex
                  ? {
                      ...o,
                      responses: o.responses.map((r, k) => (k === responseIndex ? { ...r, ...patch } : r)),
                    }
                  : o
              ),
            }
          : s
      )
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-3xl max-h-[85vh] overflow-y-auto"
        data-testid={`mock-scenario-editor-${versionRecordId}`}
      >
        <DialogHeader>
          <DialogTitle>Mock scenarios for v{versionLabel}</DialogTitle>
          <DialogDescription>
            Curated situations consumers select per request with the{' '}
            <code className="font-mono text-xs">X-Mock-Scenario</code> header. Add several responses
            to one operation to build a per-call sequence; requests without the header keep the
            default mock behavior.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="mock-scenario-loading">
            Loading scenarios…
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {drafts.length === 0 && (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                No scenarios defined yet. Add one to get started — for example{' '}
                <span className="font-mono text-xs">quota-exceeded</span> returning HTTP 429 from a
                list operation.
              </p>
            )}

            {drafts.map((scenario, scenarioIndex) => (
              <fieldset
                key={scenarioIndex}
                className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 flex flex-col gap-3"
                data-testid={`mock-scenario-${scenarioIndex}`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 flex flex-col gap-2">
                    <Input
                      value={scenario.name}
                      onChange={(e) => updateScenario(scenarioIndex, { name: e.target.value })}
                      placeholder="scenario-name (e.g. quota-exceeded)"
                      aria-label={`Scenario ${scenarioIndex + 1} name`}
                    />
                    <Input
                      value={scenario.description}
                      onChange={(e) => updateScenario(scenarioIndex, { description: e.target.value })}
                      placeholder="Description (optional)"
                      aria-label={`Scenario ${scenarioIndex + 1} description`}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => setDrafts((prev) => prev.filter((_, i) => i !== scenarioIndex))}
                    aria-label={`Remove scenario ${scenario.name || scenarioIndex + 1}`}
                  >
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </Button>
                </div>

                {scenario.operations.map((operation, operationIndex) => (
                  <div
                    key={operationIndex}
                    className="rounded-md border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 p-3 flex flex-col gap-3"
                  >
                    <div className="flex items-center gap-2">
                      <Input
                        value={operation.key}
                        onChange={(e) => updateOperation(scenarioIndex, operationIndex, { key: e.target.value })}
                        placeholder="Operation (e.g. GET /pets/{petId})"
                        aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} key`}
                        className="font-mono text-xs"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() =>
                          updateScenario(scenarioIndex, {
                            operations: scenario.operations.filter((_, j) => j !== operationIndex),
                          })
                        }
                        aria-label={`Remove operation ${operation.key || operationIndex + 1}`}
                      >
                        <Trash2 className="h-4 w-4 text-red-500" />
                      </Button>
                    </div>

                    {operation.responses.map((response, responseIndex) => (
                      <div
                        key={responseIndex}
                        className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 flex flex-col gap-2"
                      >
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">
                            {operation.responses.length > 1 ? `Call ${responseIndex + 1}` : 'Response'}
                          </span>
                          <Input
                            value={response.status}
                            onChange={(e) =>
                              updateResponse(scenarioIndex, operationIndex, responseIndex, {
                                status: e.target.value,
                              })
                            }
                            placeholder="Status"
                            aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} response ${responseIndex + 1} status`}
                            className="w-24"
                            inputMode="numeric"
                          />
                          <Input
                            value={response.mediaType}
                            onChange={(e) =>
                              updateResponse(scenarioIndex, operationIndex, responseIndex, {
                                mediaType: e.target.value,
                              })
                            }
                            placeholder="Media type (default application/json)"
                            aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} response ${responseIndex + 1} media type`}
                            className="flex-1 min-w-[12rem]"
                          />
                          <label className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300">
                            <input
                              type="checkbox"
                              checked={response.offSpec}
                              onChange={(e) =>
                                updateResponse(scenarioIndex, operationIndex, responseIndex, {
                                  offSpec: e.target.checked,
                                })
                              }
                              aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} response ${responseIndex + 1} off-spec`}
                              className="h-3.5 w-3.5 rounded border-gray-300 dark:border-gray-600"
                            />
                            Off-spec
                          </label>
                          {operation.responses.length > 1 && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                updateOperation(scenarioIndex, operationIndex, {
                                  responses: operation.responses.filter((_, k) => k !== responseIndex),
                                })
                              }
                              aria-label={`Remove response ${responseIndex + 1}`}
                            >
                              <Trash2 className="h-4 w-4 text-red-500" />
                            </Button>
                          )}
                        </div>
                        <Textarea
                          value={response.headersText}
                          onChange={(e) =>
                            updateResponse(scenarioIndex, operationIndex, responseIndex, {
                              headersText: e.target.value,
                            })
                          }
                          placeholder='Headers as JSON, e.g. {"Retry-After": "60"} (optional)'
                          aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} response ${responseIndex + 1} headers`}
                          className="font-mono text-xs min-h-[44px]"
                        />
                        <Textarea
                          value={response.bodyText}
                          onChange={(e) =>
                            updateResponse(scenarioIndex, operationIndex, responseIndex, {
                              bodyText: e.target.value,
                            })
                          }
                          placeholder="Body as JSON; leave blank for an empty response body"
                          aria-label={`Scenario ${scenarioIndex + 1} operation ${operationIndex + 1} response ${responseIndex + 1} body`}
                          className="font-mono text-xs min-h-[64px]"
                        />
                      </div>
                    ))}

                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        updateOperation(scenarioIndex, operationIndex, {
                          responses: [...operation.responses, { ...EMPTY_RESPONSE }],
                        })
                      }
                      className="self-start"
                    >
                      <Plus className="h-3.5 w-3.5" /> Add sequence step
                    </Button>
                  </div>
                ))}

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    updateScenario(scenarioIndex, {
                      operations: [...scenario.operations, { key: '', responses: [{ ...EMPTY_RESPONSE }] }],
                    })
                  }
                  className="self-start"
                >
                  <Plus className="h-3.5 w-3.5" /> Add operation override
                </Button>
              </fieldset>
            ))}

            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                setDrafts((prev) => [...prev, { name: '', description: '', operations: [] }])
              }
              className="self-start"
              data-testid="mock-scenario-add"
            >
              <Plus className="h-4 w-4" /> Add scenario
            </Button>

            {errors.length > 0 && (
              <div
                className="rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-3"
                data-testid="mock-scenario-errors"
              >
                <p className="text-sm font-semibold text-red-700 dark:text-red-300">
                  Please fix the following before saving:
                </p>
                <ul className="mt-1 list-disc pl-5 text-xs text-red-700 dark:text-red-300">
                  {errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                Cancel
              </Button>
              <Button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                data-testid="mock-scenario-save"
              >
                {saving ? 'Saving…' : 'Save scenarios'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
