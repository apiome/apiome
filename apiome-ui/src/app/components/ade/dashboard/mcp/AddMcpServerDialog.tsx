'use client';

/**
 * The Add MCP server dialog.
 *
 * Opened by **Add MCP server** on the MCP servers pages. It used to be the Import specification
 * wizard opened on its MCP tab, which brought that wizard's spec stepper, its row of every spec
 * source and its import-jobs drawer along. This dialog shows only what adding a server needs:
 *
 * 1. **Connect** — the {@link McpImportPanel} form: one server (URL, name, transport, auth) or
 *    every server a registry lists.
 * 2. **Discover** — one server is registered, its credential stored and a discovery run started;
 *    {@link McpDiscoveryPanel} follows the run to its grade.
 * 3. **Done** — what landed, with a link to it.
 *
 * It reuses the import wizard's frame (head, stepper, body, footer) so it looks like the rest of
 * the intake dialogs, and its footer comes from {@link addMcpServerFooterFor}.
 *
 * A server is *committed* once its scan succeeds, or once the user picks **Add this server
 * anyway** after a failed one. An uncommitted server is deleted on Back, Discard and close, so a
 * failed connection never lingers in the catalog.
 */

import { useState } from 'react';
import { Network } from 'lucide-react';

import { Dialog, DialogContent } from '../../../ui/Dialog';
import { Alert } from '../../../ui/Alert';
import McpImportPanel from '../McpImportPanel';
import McpDiscoveryPanel from '../McpDiscoveryPanel';
import { McpImportDonePanel } from '../../import/McpImportDonePanel';
import { McpRegistryImportDonePanel } from '../../import/McpRegistryImportDonePanel';
import { ImportWizardBody, ImportWizardFooter, ImportWizardHead, ImportWizardSteps } from '../../import/ImportWizardChrome';
import {
  buildCreateEndpointBody,
  buildCredentialBody,
  emptyMcpImportForm,
  validateMcpImportForm,
  type McpImportForm,
} from './mcpImportFlow';
import {
  buildRegistryConnectorDraft,
  buildRegistryCredentials,
  registryRunFailed,
  summarizeRegistryRun,
  type RegistryImportSummary,
} from './mcpRegistryImport';
import { createConnector, deleteConnector, syncConnector } from '@lib/connectors-api';
import {
  ADD_MCP_SERVER_COPY,
  ADD_MCP_SERVER_STEPS,
  addMcpServerFooterFor,
  type AddMcpServerStep,
} from './addMcpServerModel';

export interface AddMcpServerDialogProps {
  open: boolean;
  /** Called when the dialog closes, whatever happened. */
  onClose: () => void;
  /** Called on close when a server (or a registry's servers) landed, so the list can refresh. */
  onSuccess?: () => void;
}

/** Read a route's `{ error }` message, falling back to `fallback`. */
async function errorFrom(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return typeof data.error === 'string' ? data.error : fallback;
}

/** Delete a catalog endpoint, best-effort: a failure is ignored (the server soft-deletes it). */
async function deleteEndpoint(id: string): Promise<void> {
  try {
    await fetch(`/api/mcp/endpoints/${encodeURIComponent(id)}`, { method: 'DELETE', credentials: 'include' });
  } catch {
    // Best-effort cleanup.
  }
}

/**
 * The dialog.
 *
 * @param props See {@link AddMcpServerDialogProps}.
 * @returns The dialog, rendered only while `open`.
 */
export default function AddMcpServerDialog({ open, onClose, onSuccess }: AddMcpServerDialogProps) {
  const [step, setStep] = useState<AddMcpServerStep>('connect');
  const [form, setForm] = useState<McpImportForm>(emptyMcpImportForm);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [endpointId, setEndpointId] = useState<string | null>(null);
  const [endpointName, setEndpointName] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [scanComplete, setScanComplete] = useState(false);
  const [scanSucceeded, setScanSucceeded] = useState(false);
  const [committed, setCommitted] = useState(false);
  /** A finished registry import: its connector and what the first sync did. */
  const [registryImport, setRegistryImport] = useState<{ connectorId: string; summary: RegistryImportSummary } | null>(
    null
  );

  const registry = form.mode === 'registry';

  const reset = () => {
    setStep('connect');
    setForm(emptyMcpImportForm());
    setSubmitting(false);
    setErrorMessage(null);
    setEndpointId(null);
    setEndpointName('');
    setJobId(null);
    setScanComplete(false);
    setScanSucceeded(false);
    setCommitted(false);
    setRegistryImport(null);
  };

  /** Close the dialog, deleting an uncommitted server and refreshing the list if anything landed. */
  const close = async () => {
    if (endpointId && !committed) await deleteEndpoint(endpointId);
    if ((committed || registryImport) && onSuccess) onSuccess();
    reset();
    onClose();
  };

  /**
   * One server: create the endpoint, store its credential (when an auth type was chosen) and
   * start a discovery run, then move to Discover. If any of the three fails, the endpoint just
   * created is deleted and the reason shown on the form.
   */
  const startDiscovery = async () => {
    setErrorMessage(null);
    setSubmitting(true);
    let createdId: string | null = null;
    try {
      const createBody = buildCreateEndpointBody(form);
      const createRes = await fetch('/api/mcp/endpoints', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createBody),
      });
      if (!createRes.ok) throw new Error(await errorFrom(createRes, 'Could not register the MCP server.'));
      const endpoint = ((await createRes.json().catch(() => ({}))) as { endpoint?: { id?: string; name?: string } })
        .endpoint;
      if (!endpoint?.id) throw new Error('The MCP server was created but no id was returned.');
      createdId = endpoint.id;

      const credentialBody = buildCredentialBody(form);
      if (credentialBody) {
        const credRes = await fetch(`/api/mcp/endpoints/${encodeURIComponent(createdId)}/credentials`, {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(credentialBody),
        });
        if (!credRes.ok) throw new Error(await errorFrom(credRes, 'Could not store the credential.'));
      }

      const discoverRes = await fetch(`/api/mcp/endpoints/${encodeURIComponent(createdId)}/discover`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!discoverRes.ok) throw new Error(await errorFrom(discoverRes, 'Could not start discovery.'));
      const job = ((await discoverRes.json().catch(() => ({}))) as { job?: { id?: string } }).job;
      if (!job?.id) throw new Error('Discovery did not start.');

      setEndpointId(createdId);
      setEndpointName(endpoint.name || createBody.name);
      setCommitted(false);
      setJobId(job.id);
      setScanComplete(false);
      setScanSucceeded(false);
      setStep('discover');
    } catch (error) {
      if (createdId) await deleteEndpoint(createdId);
      setErrorMessage(error instanceof Error ? error.message : 'Could not add the MCP server.');
    } finally {
      setSubmitting(false);
    }
  };

  /**
   * A registry: register an `mcp-registry` connector, store its credential and run its first sync,
   * which adds, discovers and grades every server with a reachable remote. A run that failed
   * outright imported nothing, so its connector is deleted and the reason shown on the form.
   */
  const importRegistry = async () => {
    setErrorMessage(null);
    setSubmitting(true);
    let connectorId: string | null = null;
    try {
      const connector = await createConnector(
        buildRegistryConnectorDraft(form.registry),
        buildRegistryCredentials(form.registry)
      );
      connectorId = connector.id;
      const run = await syncConnector(connector.id);
      if (registryRunFailed(run)) {
        await deleteConnector(connector.id).catch(() => undefined);
        setErrorMessage(run.errorMessage || 'The registry could not be read.');
        return;
      }
      setRegistryImport({ connectorId: connector.id, summary: summarizeRegistryRun(run) });
      setStep('done');
    } catch (error) {
      if (connectorId) await deleteConnector(connectorId).catch(() => undefined);
      setErrorMessage(error instanceof Error ? error.message : 'Could not import from the registry.');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePrimary = () => {
    if (step === 'connect') {
      const invalid = validateMcpImportForm(form);
      if (invalid) {
        setErrorMessage(invalid);
        return;
      }
      void (registry ? importRegistry() : startDiscovery());
    } else if (step === 'discover') {
      setStep('done');
    } else {
      void close();
    }
  };

  const handleBack = () => {
    setErrorMessage(null);
    if (step === 'done' && registryImport) {
      // A registry import has no Discover step: Back returns to the form (its connector stays).
      setRegistryImport(null);
      setStep('connect');
    } else if (step === 'done') {
      setStep('discover');
    } else if (step === 'discover') {
      // Back to the form; a server the user did not keep is deleted on the way.
      if (endpointId && !committed) {
        void deleteEndpoint(endpointId);
        setEndpointId(null);
        setEndpointName('');
      }
      setJobId(null);
      setScanComplete(false);
      setScanSucceeded(false);
      setStep('connect');
    }
  };

  const footer = addMcpServerFooterFor({
    step,
    ready: validateMcpImportForm(form) === null,
    submitting,
    registry,
    scanComplete,
    scanSucceeded,
  });

  const body = (() => {
    if (step === 'discover' && endpointId && jobId) {
      return (
        <McpDiscoveryPanel
          endpointId={endpointId}
          jobId={jobId}
          endpointName={endpointName}
          onComplete={(succeeded) => {
            setScanComplete(true);
            setScanSucceeded(succeeded);
            if (succeeded) setCommitted(true);
          }}
        />
      );
    }
    if (step === 'done' && registryImport) {
      return (
        <McpRegistryImportDonePanel
          connectorId={registryImport.connectorId}
          summary={registryImport.summary}
          onNavigate={() => void close()}
        />
      );
    }
    if (step === 'done') {
      return (
        <McpImportDonePanel
          endpointId={endpointId}
          endpointName={endpointName}
          succeeded={scanSucceeded}
          onNavigate={() => void close()}
        />
      );
    }
    return <McpImportPanel form={form} onChange={setForm} />;
  })();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) void close();
      }}
    >
      <DialogContent size="lg" className="imp-wizard imp-wizard--fit" data-testid="add-mcp-server-dialog">
        <ImportWizardHead
          icon={<Network />}
          title={ADD_MCP_SERVER_COPY.title}
          description={ADD_MCP_SERVER_COPY.description}
        />
        <ImportWizardSteps
          steps={ADD_MCP_SERVER_STEPS}
          current={step}
          complete={step === 'done'}
          label={ADD_MCP_SERVER_COPY.stepsLabel}
        />
        <ImportWizardBody>
          {errorMessage ? (
            <Alert variant="danger" className="mb-4">
              {errorMessage}
            </Alert>
          ) : null}
          {body}
        </ImportWizardBody>
        <ImportWizardFooter
          footer={footer}
          onBack={handleBack}
          onCancel={() => void close()}
          onPrimary={handlePrimary}
          onKeepAnyway={() => {
            setCommitted(true);
            setStep('done');
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
