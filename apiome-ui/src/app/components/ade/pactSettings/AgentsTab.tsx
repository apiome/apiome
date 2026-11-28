'use client';

/**
 * **Settings → Agents** — PFX-8.15 (#7312), built to `docs/mockups/contracts/settings.html`.
 *
 * What an AI agent connected through Apiome's MCP server may do with contracts: read pacts, verdicts
 * and can-i-deploy (on), draft a pact (on), publish (off) and record deployments (off). Reading is on;
 * anything that writes is the workspace's to allow. An action switched off is refused to the agent
 * with the reason and audited (`pacts.agent.refused`); an agent never records a deployment to an
 * environment marked production. No agent tool drafts or publishes yet — those rows say so.
 * **Save switches** is the tab's one primary.
 */

import * as React from 'react';
import { Badge } from '@/app/components/ui/Badge';
import { CommandBlock, LoadingState } from '@/app/components/ui';
import { pactCommandSurfaces, tenantPath, unsupportedLines } from '@lib/pact-commands';
import { AGENTS_PROXY_PATH, AGENT_SWITCHES, type ContractSettings } from '@lib/pact-contract-settings';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { SectionError } from '../pactVerification/PactVerificationClient';
import { fetchContractSettings, saveAgents } from './contractSettingsApi';
import { ReadOnlyNote } from './ReadOnlyNote';
import { SwitchList } from './SwitchList';

/** Why the block shows only REST: no `apiome pact` command changes these switches. */
export const AGENTS_HAVE_NO_COMMAND =
  'No apiome pact command changes what agents may do; use this tab or the REST request.';

/**
 * The Agents tab.
 *
 * @returns The tab's content.
 */
export default function AgentsTab() {
  const [settings, setSettings] = React.useState<ContractSettings | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setSettings(null);
    setError(null);
    try {
      setSettings(await fetchContractSettings());
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load what agents may do'));
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const action = settings
    ? {
        verb: null,
        noCommandReason: AGENTS_HAVE_NO_COMMAND,
        rest: { method: 'PUT', path: tenantPath('', `/${AGENTS_PROXY_PATH}`), body: settings.agents },
      }
    : null;

  return (
    <div className="pcx" data-testid="pact-settings-agents">
      {settings && !settings.can_edit ? <ReadOnlyNote what="what agents may do" /> : null}
      <div className="pcx-split">
        <div className="pcx-split__main">
          <section className="ppx__panel" aria-labelledby="pag-title" data-testid="pag-agents">
            <div className="ppx__panel-head">
              <h2 id="pag-title" className="ppx__title">
                What an AI agent may do with contracts
              </h2>
              <Badge variant="secondary">MCP</Badge>
            </div>
            <p className="ppx__muted">
              Agents connected through Apiome’s MCP server see contracts as tools. Reading is on; anything that writes is
              yours to allow. A refused action tells the agent why and is written to the access audit.
            </p>
            {error ? (
              <SectionError title="The switches could not be read" error={error} onRetry={() => void load()} />
            ) : !settings ? (
              <LoadingState message="Reading the switches…" minHeightClassName="min-h-[4rem]" />
            ) : (
              <SwitchList
                id="pag"
                specs={AGENT_SWITCHES}
                saved={settings.agents}
                readOnly={!settings.can_edit}
                saveLabel="Save switches"
                onSave={async (values) => setSettings(await saveAgents(values))}
              />
            )}
          </section>
        </div>
        <aside className="pcx-split__aside" aria-label="Agents from anywhere">
          {action ? (
            <section className="ppx__panel" aria-labelledby="pag-command-title">
              <h2 id="pag-command-title" className="pcx-caps">
                The same, from anywhere
              </h2>
              <CommandBlock
                surfaces={pactCommandSurfaces(action)}
                defaultSurface="rest"
                unsupported={unsupportedLines(action)}
                footnote="Replace {tenant} with your workspace’s handle in the REST path."
                data-testid="pag-command-block"
              />
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
