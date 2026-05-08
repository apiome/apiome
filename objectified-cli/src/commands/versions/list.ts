import { Args, Flags } from "@oclif/core";

import { BaseCommand } from "../../base-command.js";
import { ObjectifiedCliError } from "../../lib/errors.js";
import { EXIT_CODES } from "../../lib/exit-codes.js";
import { chalkForContext } from "../../lib/output.js";
import { completionProfileCacheKey, resolveProjectForTenant } from "../../lib/resolve.js";
import {
  applyVersionsListPipeline,
  parseVersionsSortField,
  parseVersionStateFilter,
} from "../../lib/versions/list-query.js";
import {
  buildTagsByRevisionId,
  formatVersionsListHumanLines,
} from "../../lib/versions/list-format.js";

const LIMIT_MAX = 500;
const DEFAULT_LIMIT = 10;

export default class VersionsList extends BaseCommand {
  static description =
    "List schema versions for a project (GET /v1/versions/{tenant_slug}/{project_id}; tags joined from version tags)";

  static examples = [
    "<%= config.bin %> <%= command.id %> payments-api",
    "<%= config.bin %> --json <%= command.id %> payments-api",
    "<%= config.bin %> <%= command.id %> payments-api --state draft,published --limit 25",
    "<%= config.bin %> <%= command.id %> payments-api --sort published_at --reverse",
    "<%= config.bin %> --profile staging <%= command.id %> my-api --all",
  ];

  static seeAlso = ["projects show", "projects list", "tenants use", "docs errors"];

  static args = {
    project: Args.string({
      description: "Project slug or UUID (uuid-shaped refs resolve as id first)",
      required: true,
    }),
  };

  static flags = {
    state: Flags.string({
      description:
        "Comma-separated filters (OR): draft, published, archived, frozen. Matches CLI-derived states.",
    }),
    limit: Flags.integer({
      description: `Maximum rows after sort/filter (1–${String(LIMIT_MAX)}; default ${String(DEFAULT_LIMIT)}). Ignored with --all.`,
      min: 1,
      max: LIMIT_MAX,
      default: DEFAULT_LIMIT,
    }),
    all: Flags.boolean({
      description: "List every matching version after sort/filter (no --limit cap).",
      default: false,
    }),
    sort: Flags.string({
      description: "Sort by version, published_at, or created_at (default: version).",
    }),
    reverse: Flags.boolean({
      description: "Reverse the default sort direction (defaults are descending).",
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

    const argv = this.normalizedArgv;
    const hasAllFlag = argv.some((a) => a === "--all" || a.startsWith("--all="));
    const hasLimitFlag = argv.some((a) => a === "--limit" || a.startsWith("--limit="));
    if (hasAllFlag && hasLimitFlag) {
      throw new ObjectifiedCliError({
        message: "Cannot use --all together with --limit.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Pass only one of --all or --limit.",
      });
    }

    let stateFilter;
    let sortField;
    try {
      stateFilter = parseVersionStateFilter(this.flags.state as string | undefined);
      sortField = parseVersionsSortField(this.flags.sort as string | undefined);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new ObjectifiedCliError({
        message: msg,
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Run `objectified versions list --help` for flag syntax.",
      });
    }

    const rawProjectArg = this.commandArgs.project;
    const projectArg = typeof rawProjectArg === "string" ? rawProjectArg : "";

    this.ensureAuthenticated();

    const profileKey = completionProfileCacheKey({
      baseUrl: this.context.baseUrl,
      profile: this.context.profile,
      tenantSlug: tenant,
    });

    const project = await resolveProjectForTenant(this.api, tenant, projectArg, profileKey);

    const [versions, tags] = await Promise.all([
      this.api.listVersions(tenant, project.id),
      this.api.listVersionTags(tenant, project.id),
    ]);

    const tagsByRevisionId = buildTagsByRevisionId(tags);

    const pipeline = applyVersionsListPipeline(versions, {
      stateFilter,
      sortField,
      reverse: this.flags.reverse === true,
    });

    const useAll = Boolean(this.flags.all);
    const limitRaw = this.flags.limit as number | undefined;
    const limit = Math.min(LIMIT_MAX, Math.max(1, limitRaw ?? DEFAULT_LIMIT));
    const displayed = useAll ? pipeline : pipeline.slice(0, limit);
    const truncated = !useAll && pipeline.length > displayed.length;

    const projectLabel = project.slug;

    if (this.context.json) {
      this.output.json(displayed);
      return;
    }

    const c = chalkForContext(this.context.color);

    if (versions.length === 0) {
      this.output.text(`${c.bold("No versions yet.")} Project '${projectLabel}' has no schema revisions.`);
      return;
    }

    if (pipeline.length === 0) {
      this.output.text("No versions match your --state filter.");
      return;
    }

    const useGlyphForFrozen = this.context.color;
    const freezeGlyph = useGlyphForFrozen ? c.cyan("❄") : "";
    const freezeBracket = " [frozen]";

    const lines = formatVersionsListHumanLines({
      versions: displayed,
      tagsByRevisionId,
      projectLabel,
      truncated,
      totalAfterPipeline: pipeline.length,
      useGlyphForFrozen,
      freezeGlyph,
      freezeBracket,
    });
    for (const line of lines) {
      this.output.text(line);
    }
  }
}
