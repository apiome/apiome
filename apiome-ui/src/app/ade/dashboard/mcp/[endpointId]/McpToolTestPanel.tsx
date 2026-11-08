'use client';

/**
 * The MCP endpoint **Test** tab (V2-MCP-22.4 / V2-MCP-24.5, #3690 / #3701).
 *
 * Pick a discovered tool, fill the argument form generated from its `inputSchema`, and run it
 * against the live server through the test harness (MCAT-8.2). The call uses the endpoint's
 * stored credential; when none is stored the tab says so, since the call then runs anonymously.
 * A tool flagged `destructiveHint` / `openWorldHint` cannot be run until the confirm box is
 * ticked — the server enforces the same gate (428), so the box only makes it visible first.
 *
 * The result card shows the outcome (succeeded / tool error / call failed), the mockup's
 * `142 ms · isError: false` line, the returned content, any `structuredContent`, and the
 * classified error when the call never returned.
 *
 * The form logic lives in {@link ../../../../components/ade/dashboard/mcp/mcpTestUi}.
 */

import * as React from 'react';
import { FlaskConical, KeyRound, Loader2, Play, TriangleAlert, Wrench } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardBody, CardHeader, CardTitle } from '@/app/components/ui/Card';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { McpJsonViewer } from '@/app/components/ui/mcp/McpJsonViewer';
import type { McpCapabilityItem } from '@/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  mcpBuildToolArguments,
  mcpInitialArgumentValues,
  mcpTestableTools,
  mcpTestContentText,
  mcpTestIsTextContent,
  mcpTestCredentialMissing,
  mcpTestOutcome,
  mcpTestResultFromPayload,
  mcpTestSummaryLine,
  mcpToolArgumentFields,
  mcpToolConfirmHints,
  type McpArgumentField,
  type McpArgumentValues,
  type McpTestResult,
} from '@/app/components/ade/dashboard/mcp/mcpTestUi';

export interface McpToolTestPanelProps {
  /** The endpoint whose tools are tested. */
  endpointId: string;
  /** The current version's capability items, or `null` when the endpoint is undiscovered. */
  items: readonly McpCapabilityItem[] | null;
}

/** Sentinel for an unset enum picker (Radix Select forbids an empty-string item value). */
const ENUM_UNSET = '__unset__';

/** One argument input, chosen by the field's kind. */
function ArgumentInput({
  field,
  value,
  error,
  onChange,
}: {
  field: McpArgumentField;
  value: string | boolean;
  error?: string;
  onChange: (value: string | boolean) => void;
}) {
  const id = `mcp-test-arg-${field.name}`;
  if (field.kind === 'boolean') {
    return (
      <div className="mcp-test-check">
        <Checkbox
          id={id}
          checked={value === true}
          onCheckedChange={(checked) => onChange(checked === true)}
          data-testid={id}
        />
        <Label htmlFor={id}>{field.label}</Label>
        {field.description ? <span className="mcp-test-check__help">{field.description}</span> : null}
      </div>
    );
  }
  return (
    <FormField
      label={field.label}
      htmlFor={id}
      required={field.required}
      helperText={field.description ?? undefined}
      error={error}
      className={field.kind === 'json' ? 'mcp-settings-fields__wide' : undefined}
    >
      {field.kind === 'enum' ? (
        <Select
          value={typeof value === 'string' && value !== '' ? value : ENUM_UNSET}
          onValueChange={(next) => onChange(next === ENUM_UNSET ? '' : next)}
        >
          <SelectTrigger id={id} data-testid={id}>
            <SelectValue placeholder="Choose a value" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ENUM_UNSET}>Not set</SelectItem>
            {field.enumValues.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.kind === 'json' ? (
        <Textarea
          id={id}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value)}
          placeholder="JSON value"
          className="mono"
          rows={4}
          data-testid={id}
        />
      ) : (
        <Input
          id={id}
          type={field.kind === 'string' ? 'text' : 'number'}
          step={field.kind === 'integer' ? 1 : 'any'}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value)}
          data-testid={id}
        />
      )}
    </FormField>
  );
}

/** The outcome of the last run. */
function TestResultCard({ result }: { result: McpTestResult }) {
  const outcome = mcpTestOutcome(result);
  return (
    <Card data-testid="mcp-test-result">
      <CardHeader className="flex-row items-center gap-2">
        <FlaskConical aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
        <CardTitle>Result</CardTitle>
        <Badge status={outcome.status} data-testid="mcp-test-outcome">
          {outcome.label}
        </Badge>
        <span className="mcp-test-result__meta mono" data-testid="mcp-test-summary">
          {mcpTestSummaryLine(result)}
        </span>
      </CardHeader>
      <CardBody className="mcp-test-result">
        <p className="mcp-test-result__target">
          <span className="mono">{result.method}</span> → <span className="mono">{result.target}</span>
        </p>
        {result.error ? (
          <Alert variant="danger" data-testid="mcp-test-error">
            <AlertTitle>{result.error.code ?? 'Error'}</AlertTitle>
            <AlertDescription>{result.error.message ?? 'The call did not return a result.'}</AlertDescription>
          </Alert>
        ) : null}
        {result.content.length > 0 ? (
          <div className="mcp-test-result__content" data-testid="mcp-test-content">
            {result.content.map((item, index) =>
              mcpTestIsTextContent(item) ? (
                <pre key={index} className="mcp-test-result__text">
                  {mcpTestContentText(item)}
                </pre>
              ) : (
                <McpJsonViewer key={index} value={mcpTestContentText(item)} />
              ),
            )}
          </div>
        ) : result.completed ? (
          <p className="mcp-test-result__empty">The tool returned no content.</p>
        ) : null}
        {result.structuredContent ? (
          <div className="mcp-test-result__content" data-testid="mcp-test-structured">
            <h4 className="mcp-test-result__label">Structured content</h4>
            <McpJsonViewer value={JSON.stringify(result.structuredContent, null, 2)} />
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/**
 * The Test tab panel.
 *
 * @param props See {@link McpToolTestPanelProps}.
 * @returns The tool picker, argument form, confirm gate and result viewer.
 */
export default function McpToolTestPanel({ endpointId, items }: McpToolTestPanelProps) {
  const tools = React.useMemo(() => mcpTestableTools(items), [items]);
  const [toolName, setToolName] = React.useState<string>('');
  const [values, setValues] = React.useState<McpArgumentValues>({});
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [requestError, setRequestError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<McpTestResult | null>(null);
  /** The stored credential's `auth_type` (`none` when absent), or `null` while unknown. */
  const [authType, setAuthType] = React.useState<string | null>(null);

  const tool = tools.find((candidate) => candidate.name === toolName) ?? null;
  const fields = React.useMemo(() => mcpToolArgumentFields(tool?.input_schema), [tool]);
  const confirmHints = mcpToolConfirmHints(tool);
  const needsConfirm = confirmHints.length > 0;

  // Start on the first tool once the surface loads.
  React.useEffect(() => {
    if (!toolName && tools.length > 0) setToolName(tools[0].name);
  }, [toolName, tools]);

  // A new tool resets the form to its schema defaults and clears the last run.
  React.useEffect(() => {
    setValues(mcpInitialArgumentValues(fields, tool?.input_schema));
    setFieldErrors({});
    setConfirmed(false);
    setRequestError(null);
    setResult(null);
  }, [fields, tool]);

  // Read the redacted credential status once, to surface a missing credential.
  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
          credentials: 'include',
          cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        const credential = data && typeof data === 'object' ? data.credential : null;
        if (active) {
          setAuthType(res.ok && typeof credential?.auth_type === 'string' ? credential.auth_type : null);
        }
      } catch {
        if (active) setAuthType(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  const run = React.useCallback(async () => {
    if (!tool) return;
    const built = mcpBuildToolArguments(fields, values);
    setFieldErrors(built.errors);
    if (Object.keys(built.errors).length > 0) return;
    setRunning(true);
    setRequestError(null);
    setResult(null);
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/test`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_type: 'tool',
          item_name: tool.name,
          arguments: built.arguments,
          confirm: needsConfirm && confirmed,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      setResult(mcpTestResultFromPayload(data));
    } catch (e) {
      setRequestError(e instanceof Error ? e.message : 'The test call could not be sent.');
    } finally {
      setRunning(false);
    }
  }, [confirmed, endpointId, fields, needsConfirm, tool, values]);

  if (items === null) {
    return (
      <EmptyState
        icon={<FlaskConical aria-hidden />}
        title="Nothing to test yet"
        description="Run discovery to capture this server's tools, then test them here."
        data-testid="mcp-test-undiscovered"
      />
    );
  }
  if (tools.length === 0) {
    return (
      <EmptyState
        icon={<Wrench aria-hidden />}
        title="No tools to test"
        description="The current snapshot declares no tools."
        data-testid="mcp-test-no-tools"
      />
    );
  }

  return (
    <div className="mcp-ep-panel" data-testid="mcp-test-panel">
      {mcpTestCredentialMissing(authType) ? (
        <Alert variant="info" icon={<KeyRound aria-hidden />} data-testid="mcp-test-no-credential">
          <AlertTitle>No stored credential</AlertTitle>
          <AlertDescription>
            Test calls run anonymously. If this server needs authentication, store a credential
            for the endpoint first.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Wrench aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
          <CardTitle>Run a tool</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-4">
          <FormField label="Tool" htmlFor="mcp-test-tool" helperText={tool?.description ?? undefined}>
            <Select value={toolName} onValueChange={setToolName}>
              <SelectTrigger id="mcp-test-tool" data-testid="mcp-test-tool">
                <SelectValue placeholder="Choose a tool" />
              </SelectTrigger>
              <SelectContent>
                {tools.map((candidate) => (
                  <SelectItem key={candidate.name} value={candidate.name}>
                    {candidate.title ?? candidate.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          {fields.length > 0 ? (
            <div className="mcp-settings-fields" data-testid="mcp-test-fields">
              {fields.map((field) => (
                <ArgumentInput
                  key={field.name}
                  field={field}
                  value={values[field.name] ?? ''}
                  error={fieldErrors[field.name]}
                  onChange={(next) => setValues((prev) => ({ ...prev, [field.name]: next }))}
                />
              ))}
            </div>
          ) : (
            <p className="mcp-test-result__empty" data-testid="mcp-test-no-args">
              This tool takes no arguments.
            </p>
          )}

          {needsConfirm ? (
            <Alert variant="warn" icon={<TriangleAlert aria-hidden />} data-testid="mcp-test-confirm">
              <AlertTitle>This tool is flagged {confirmHints.join(' and ')}</AlertTitle>
              <AlertDescription>
                <span className="mcp-test-check">
                  <Checkbox
                    id="mcp-test-confirm-box"
                    checked={confirmed}
                    onCheckedChange={(checked) => setConfirmed(checked === true)}
                    data-testid="mcp-test-confirm-box"
                  />
                  <Label htmlFor="mcp-test-confirm-box">
                    I understand this call runs against the live server and may change data.
                  </Label>
                </span>
              </AlertDescription>
            </Alert>
          ) : null}

          {requestError ? (
            <p role="alert" className="mcp-test-request-error" data-testid="mcp-test-request-error">
              <TriangleAlert aria-hidden className="size-4 shrink-0 text-danger" />
              {requestError}
            </p>
          ) : null}

          <div className="mcp-settings-actions">
            <Button
              type="button"
              onClick={() => void run()}
              disabled={running || !tool || (needsConfirm && !confirmed)}
              title={needsConfirm && !confirmed ? 'Confirm the warning above to run this tool' : 'Run this tool now'}
              data-testid="mcp-test-run"
            >
              {running ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
              {running ? 'Running…' : 'Run test'}
            </Button>
          </div>
        </CardBody>
      </Card>

      {result ? <TestResultCard result={result} /> : null}
    </div>
  );
}
