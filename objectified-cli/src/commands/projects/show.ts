import { Args } from "@oclif/core";

import { BaseCommand } from "../../base-command.js";
import { ObjectifiedCliError } from "../../lib/errors.js";
import { EXIT_CODES } from "../../lib/exit-codes.js";
import { formatProjectsShowHumanLines } from "../../lib/projects/show-format.js";
import { chalkForContext, localePrefersAsciiTable, stableDeepSort } from "../../lib/output.js";
import { completionProfileCacheKey, resolveProjectForTenant } from "../../lib/resolve.js";

export default class ProjectsShow extends BaseCommand {
  static description =
    "Show one project by slug or UUID (GET /v1/projects/{tenant}/{id} or …/by-slug/{slug})";

  static examples = [
    "<%= config.bin %> <%= command.id %> payments-api",
    "<%= config.bin %> --json <%= command.id %> payments-api",
    "<%= config.bin %> <%= command.id %> 33333333-4444-5555-6666-777777777777",
    "<%= config.bin %> --profile staging <%= command.id %> my-project",
  ];

  static seeAlso = ["projects list", "tenants use", "docs errors"];

  static args = {
    ref: Args.string({
      description: "Project slug or project UUID (uuid-shaped refs resolve as id first)",
      required: true,
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

    const rawRef = this.commandArgs.ref;
    const ref = typeof rawRef === "string" ? rawRef : "";

    this.ensureAuthenticated();

    const profileKey = completionProfileCacheKey({
      baseUrl: this.context.baseUrl,
      profile: this.context.profile,
      tenantSlug: tenant,
    });

    const project = await resolveProjectForTenant(this.api, tenant, ref, profileKey);

    const [versions, tags, auditPage] = await Promise.all([
      this.api.listVersions(tenant, project.id),
      this.api.listVersionTags(tenant, project.id),
      this.api.listWorkflowAudit({
        tenantSlug: tenant,
        projectId: project.id,
        limit: 10,
        offset: 0,
      }),
    ]);

    const activity = auditPage.items.slice(0, 10);

    if (this.context.json) {
      const composite = { ...(project as Record<string, unknown>), activity };
      this.output.json(stableDeepSort(composite));
      return;
    }

    const c = chalkForContext(this.context.color);
    const langAscii = localePrefersAsciiTable(process.env);
    const separator = langAscii ? "-".repeat(61) : "─".repeat(61);

    const lines = formatProjectsShowHumanLines({
      project,
      tenantSlug: tenant,
      versions,
      tags,
      activity,
      titleBold: (s) => c.bold(s),
      separator,
    });
    for (const line of lines) {
      this.output.text(line);
    }
  }
}
