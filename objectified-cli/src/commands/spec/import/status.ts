import { Args, Flags } from "@oclif/core";

import { BaseCommand } from "../../../base-command.js";
import { ObjectifiedCliError } from "../../../lib/errors.js";
import { EXIT_CODES } from "../../../lib/exit-codes.js";
import {
  formatImportJobStatusHumanLines,
  progressSpinnerText,
  throwIfImportJobWatchTerminalFailure,
} from "../../../lib/spec/import-job-display.js";
import { followImportJobPoll } from "../../../lib/spec/import-job-follow.js";
import { resolveImportJobRef } from "../../../lib/spec/import-job-resolver.js";
import { stableDeepSort } from "../../../lib/output.js";

export default class SpecImportStatus extends BaseCommand {
  static description =
    "Show import job status (GET /v1/imports/{tenant_slug}/{job_id}); --watch polls until a terminal state";

  static examples = [
    "<%= config.bin %> <%= command.id %> 7c3d2a1b-…-e22a",
    "<%= config.bin %> <%= command.id %> --last",
    "<%= config.bin %> --json <%= command.id %> --last",
    "<%= config.bin %> <%= command.id %> --last --watch",
  ];

  static seeAlso = ["spec import", "spec import commit", "spec import cancel", "docs errors"];

  static args = {
    jobId: Args.string({
      description: "Import job UUID (optional when --last reads ~/.cache/objectified/last-import-job-<tenant>.txt)",
      required: false,
    }),
  };

  static flags = {
    last: Flags.boolean({
      description: "Use the latest job id cached for this tenant after a successful spec import POST.",
      default: false,
    }),
    watch: Flags.boolean({
      description: "Re-poll every second until a terminal state (exit codes match spec import polling).",
      default: false,
    }),
  };

  async run(): Promise<void> {
    const tenant = this.context.tenantSlug;
    if (tenant === undefined || tenant === "") {
      throw new ObjectifiedCliError({
        message:
          "Tenant slug is required for this command. Pass --tenant, set OBJECTIFIED_TENANT, or configure tenant_slug for your profile.",
        exitCode: EXIT_CODES.CONFIG,
        title: "Configuration error",
        hint: "Run `objectified tenants use <slug>` to save a default tenant, or `objectified tenants list` to see accessible tenants.",
      });
    }

    const rawJob = this.commandArgs.jobId;
    const jobArg = typeof rawJob === "string" ? rawJob : undefined;
    const jobId = resolveImportJobRef({
      tenantSlug: tenant,
      positionalJobId: jobArg,
      last: this.flags.last === true,
    });

    this.ensureAuthenticated();

    let job = await this.api.getImportJob(tenant, jobId);

    if (this.flags.watch === true) {
      const showSpinner = !this.context.json && !this.flags.quiet;
      const { job: polled } = await followImportJobPoll({
        api: this.api,
        tenantSlug: tenant,
        initial: job,
        reviewMode: false,
        ndjson: false,
        verbose: this.verboseEffective,
        showSpinner,
        reportSink: undefined,
        spinnerText: progressSpinnerText,
        createSpinner: (t) => this.output.spinner(t),
        stderrLine: (line) => {
          process.stderr.write(`${line}\n`);
        },
      });
      job = polled;
    }

    if (this.context.json) {
      this.output.json(stableDeepSort(job));
    } else {
      for (const line of formatImportJobStatusHumanLines(job, tenant)) {
        this.output.text(line);
      }
    }

    if (this.flags.watch === true) {
      throwIfImportJobWatchTerminalFailure(job, {
        lastRequestId: this.api.lastRequestId,
        lastRetriesAttempted: this.api.lastRetriesAttempted,
      });
    }
  }
}
