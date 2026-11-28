'use client';

/**
 * **Settings → CI and commit statuses** — PFX-8.15 (#7312), built to `docs/mockups/contracts/settings.html`.
 *
 * * **Commit statuses** — three switches: on the consumer's commit, on the provider's commit, and for
 *   bi-directional verdicts too (a spec comparison then sets its statuses and fires its verification
 *   webhooks). **Save switches** is the tab's one primary. A status a switch keeps off is still
 *   recorded, as suppressed with the reason.
 * * **Pipeline recipes** — a working pipeline for GitHub Actions, GitLab CI, Jenkins and Azure
 *   Pipelines, copied from their tested sources (`lib/pact-ci-recipes.generated.ts`).
 * * **Broker address** — the two variables every Pact tool reads, and a link to create a key.
 */

import * as React from 'react';
import Link from 'next/link';
import { KeyRound } from 'lucide-react';
import { Button, CommandBlock, LoadingState } from '@/app/components/ui';
import { pactCommandSurfaces, tenantPath, unsupportedLines } from '@lib/pact-commands';
import { PACT_CI_RECIPES, type PactCiRecipe } from '@lib/pact-ci-recipes.generated';
import {
  COMMIT_STATUSES_PROXY_PATH,
  COMMIT_SWITCHES,
  type CommitStatusSettings,
  type ContractSettings,
} from '@lib/pact-contract-settings';
import { SETUP_ROUTE } from '@lib/pact-setup';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { fetchBrokerAddress, fetchContractSettings, saveCommitStatuses } from './contractSettingsApi';
import { ReadOnlyNote } from './ReadOnlyNote';
import { SwitchList } from './SwitchList';

/** Where **Create a key with Pact scopes** goes. */
export const API_KEYS_ROUTE = '/ade/dashboard/api-keys';

/** Why the block shows only REST: no `apiome pact` command changes these switches. */
export const SWITCHES_HAVE_NO_COMMAND =
  'No apiome pact command changes the commit-status switches (Pact CLI has none either); use this tab or REST.';

/**
 * The recipe picker and the recipe.
 *
 * @returns The panel.
 */
function Recipes() {
  const [chosen, setChosen] = React.useState<PactCiRecipe['id']>('github');
  const recipe = PACT_CI_RECIPES.find((item) => item.id === chosen) ?? PACT_CI_RECIPES[0];
  return (
    <Panel id="pci-recipes" title="Pipeline recipes">
      <p className="ppx__muted">
        Copy a working pipeline for a consumer and a provider: publish, ask can-i-deploy, and record the deployment.
      </p>
      <div className="pcx-chips" role="group" aria-label="CI system">
        {PACT_CI_RECIPES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="pcx-chip"
            aria-pressed={item.id === chosen}
            onClick={() => setChosen(item.id)}
            data-testid={`pci-recipe-${item.id}`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="ppx__muted">
        Save it as <span className="pcx-mono">{recipe.file}</span>.
      </p>
      <pre className="pcx-code" data-testid="pci-recipe" tabIndex={0} aria-label={`${recipe.label} recipe`}>
        {recipe.text}
      </pre>
    </Panel>
  );
}

/**
 * The CI and commit statuses tab.
 *
 * @returns The tab's content.
 */
export default function CiTab() {
  const [settings, setSettings] = React.useState<ContractSettings | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [broker, setBroker] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setSettings(null);
    setError(null);
    try {
      setSettings(await fetchContractSettings());
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the settings'));
    }
  }, []);

  React.useEffect(() => {
    void load();
    fetchBrokerAddress()
      .then(setBroker)
      .catch(() => setBroker(null));
  }, [load]);

  const switches: CommitStatusSettings | null = settings?.commit_statuses ?? null;
  const action = switches
    ? {
        verb: null,
        noCommandReason: SWITCHES_HAVE_NO_COMMAND,
        rest: { method: 'PUT', path: tenantPath('', `/${COMMIT_STATUSES_PROXY_PATH}`), body: switches },
      }
    : null;

  return (
    <div className="pcx" data-testid="pact-settings-ci">
      {settings && !settings.can_edit ? <ReadOnlyNote what="these switches" /> : null}
      <div className="pcx-split">
        <div className="pcx-split__main">
          <Panel id="pci-statuses" title="Commit statuses">
            <p className="ppx__muted">Put the contract verdict on the commit, where the pull request is decided.</p>
            {error ? (
              <SectionError title="The switches could not be read" error={error} onRetry={() => void load()} />
            ) : !settings || !switches ? (
              <LoadingState message="Reading the switches…" minHeightClassName="min-h-[4rem]" />
            ) : (
              <SwitchList
                id="pci"
                specs={COMMIT_SWITCHES}
                saved={switches}
                readOnly={!settings.can_edit}
                saveLabel="Save switches"
                onSave={async (values) => setSettings(await saveCommitStatuses(values))}
              />
            )}
            <p className="ppx__muted">
              Statuses are written to github.com and gitlab.com repositories registered in the workspace, with the
              linked account they were registered with. One a switch keeps off is listed as suppressed, with why.
            </p>
          </Panel>
          <Recipes />
        </div>
        <aside className="pcx-split__aside" aria-label="Broker address and commands">
          <section className="ppx__panel" aria-labelledby="pci-broker-title" data-testid="pci-broker">
            <h2 id="pci-broker-title" className="pcx-caps">
              Broker address
            </h2>
            <pre className="pcx-code" tabIndex={0} aria-label="The two variables">
              {`PACT_BROKER_BASE_URL=${broker ?? 'https://<api>/v1/tenants/<workspace>/pact-broker'}\nPACT_BROKER_TOKEN=<an Apiome API key>`}
            </pre>
            <p className="ppx__muted">The official Pact CLI and libraries work unchanged with these two variables.</p>
            <Button variant="outline" size="sm" asChild>
              <Link href={API_KEYS_ROUTE}>
                <KeyRound aria-hidden />
                Create a key with Pact scopes
              </Link>
            </Button>
            <Button variant="link" size="sm" asChild>
              <Link href={SETUP_ROUTE} data-testid="pci-setup">
                Open the guided set-up
              </Link>
            </Button>
          </section>
          {action ? (
            <section className="ppx__panel" aria-labelledby="pci-command-title">
              <h2 id="pci-command-title" className="pcx-caps">
                The same, from anywhere
              </h2>
              <CommandBlock
                surfaces={pactCommandSurfaces(action)}
                defaultSurface="rest"
                unsupported={unsupportedLines(action)}
                footnote="Replace {tenant} with your workspace’s handle in the REST path."
                data-testid="pci-command-block"
              />
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
