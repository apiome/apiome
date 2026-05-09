import { Args, Flags } from "@oclif/core";

import { BaseCommand } from "../../../base-command.js";
import { ObjectifiedCliError } from "../../../lib/errors.js";
import { EXIT_CODES } from "../../../lib/exit-codes.js";
import { formatShortJobId } from "../../../lib/spec/import-job-display.js";
import { ensureImportMutationConfirmed } from "../../../lib/spec/import-mutation-confirm.js";
import { resolveImportJobRef } from "../../../lib/spec/import-job-resolver.js";
import { localePrefersAsciiTable, stableDeepSort } from "../../../lib/output.js";

export default class SpecImportCancel extends BaseCommand {
  static description =
    "Cancel an import job that is not yet terminal (POST /v1/imports/{tenant_slug}/{job_id}/cancel)";

  static examples = [
    "<%= config.bin %> <%= command.id %> 7c3d2a1b-…-e22a",
    "<%= config.bin %> <%= command.id %> --last --yes",
    "<%= config.bin %> --json <%= command.id %> <job-id> --yes",
  ];

  static seeAlso = ["spec import status", "spec import commit", "spec import", "docs errors"];

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
    yes: Flags.boolean({
      description: "Skip interactive confirmation (required when stdin is not a TTY).",
      default: false,
      allowNo: false,
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

    await ensureImportMutationConfirmed({ yes: this.flags.yes === true, verbLabel: "cancel" });

    this.ensureAuthenticated();

    const job = await this.api.cancelImportJob(tenant, jobId);

    if (this.context.json) {
      this.output.json(stableDeepSort(job));
      return;
    }

    const langAscii = localePrefersAsciiTable(process.env);
    const mark = langAscii ? "[ok]" : "✔";
    const shortId = formatShortJobId(job.jobId);
    this.output.text(`${mark} Canceled job ${shortId}. Transaction rolled back.`);
  }
}
