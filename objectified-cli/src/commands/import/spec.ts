import path from "node:path";

import { Args, Flags } from "@oclif/core";

import { BaseCommand } from "../../base-command.js";
import type {
  SpecImportCommitResponse,
  SpecImportJobAccepted,
  SpecImportJobStatus,
  SpecImportRollbackResponse,
  VersionPublishRequest,
} from "../../lib/client.js";
import { ObjectifiedCliError } from "../../lib/errors.js";
import { EXIT_CODES } from "../../lib/exit-codes.js";
import { resolveSpecImportKind, type ResolvedSpecKind } from "../../lib/import/spec-format.js";
import {
  pollSpecImportUntilGate,
  pollSpecImportUntilTerminal,
} from "../../lib/import/spec-import-flow.js";
import {
  deriveCatalogIdentityFromSpecBytes,
  extractSpecInfoForCliDisplay,
  resolveCatalogIdentityForCreateOrMap,
} from "../../lib/import/spec-import-catalog-identity.js";
import { readSpecInput } from "../../lib/import/read-spec-input.js";
import {
  resolveCreateOrMapProjectImport,
  resolveCreateProjectImport,
  resolveMapProjectImport,
  throwIfConflictingImportProjectFlags,
  type ResolvedSpecImportProject,
} from "../../lib/import/spec-import-project-resolution.js";
import type { Visibility } from "../../lib/projects/project-create-body.js";
import { validateProjectSlug } from "../../lib/projects/project-slug.js";
import { resolveImportCatalogVersionId } from "../../lib/versions/create-helpers.js";

type ImportSpecSummaryJson = {
  tenant_slug: string;
  job_id: string;
  status_path?: string;
  final_state: SpecImportJobStatus["state"];
  source_kind: string;
  project_slug?: string | null;
  project_id?: string | null;
  version_id?: string | null;
  version_record_id?: string | null;
  summary?: Record<string, unknown> | null;
  commit?: SpecImportCommitResponse | null;
  rollback?: SpecImportRollbackResponse | null;
  stopped_at?: "pending-approval" | null;
  /** Present when --publish ran successfully after import */
  publish?: {
    visibility: "public" | "private";
    published: true;
    version_record_id: string;
  } | null;
};

function throwForBadTerminalState(st: SpecImportJobStatus): never {
  const tail = st.events?.slice(-3) ?? [];
  const hint =
    tail.length > 0
      ? tail.map((e) => `${e.code}: ${e.message}`).join("; ")
      : "See GET …/imports/{job_id} for full events.";
  throw new ObjectifiedCliError({
    message: `Import job ${st.job_id} ended in state ${st.state}.`,
    exitCode: EXIT_CODES.GENERIC,
    title: "Import failed",
    hint,
  });
}

export default class ImportSpec extends BaseCommand {
  static description =
    "Start a tenant-scoped specification import (POST /v1/tenants/{tenant_slug}/imports with JSON+base64), poll job status at a fixed interval, then commit (default), rollback preview, or stop after preview (`--no-commit`). Progress is logged to stderr as numbered lines (`objectified: import: [n] …`) that describe each phase in plain language — what API call runs next, what the server is doing, and import poll snapshots with lifecycle state and importer progress (use `--quiet` to suppress). Before the job starts, OpenAPI and AsyncAPI specs print an extracted summary (catalog project name/slug/version, spec title, description, and remaining `info` metadata such as contact and license). Catalog version ids default to permissive parsing with warnings when they are not strict SemVer 2.0; pass `--strict` to enforce strict semver and fail on mismatch. Use `--publish=public` or `--publish=private` to publish after import completes; that step skips server publication gates — verify the catalog yourself (CLI warns on success). `--poll` sets the interval in milliseconds between GET status polls (default 400). `--verbose` adds HTTP diagnostics and includes wait-between-polls messages. Supported formats vs the dashboard Import dialog and repository filename scanner: docs/CLI_SPEC_IMPORT_FORMAT_PARITY.md (Epic #3328).";

  static examples = [
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --project-name 'Payments API' --project-slug payments-api --version 1.0.0",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --map-project payments-api --version 1.0.0",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --create-project --project-name 'Payments API' --project-slug payments-api --version 1.0.0 --yes",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --tenant acme --create-or-map-project --yes --no-wait",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --create-or-map-project --project-name 'Payments API' --project-slug payments-api --version 1.0.0 --yes --no-wait",
    "<%= config.bin %> --json <%= command.id %> ./spec.json --project-slug my-api --project-name 'My API' --version 2.0.0 --no-wait",
    "<%= config.bin %> <%= command.id %> - --filename ./api.yaml --project-slug svc --project-name Service --version 0.1.0 < ./api.yaml",
    "<%= config.bin %> <%= command.id %> ./asyncapi.yml --project-slug events --project-name Events --version 1.0.0 --dry-run",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --create-or-map-project --yes --publish=private",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --map-project payments-api --version 1.0.0 --poll 2000",
  ];

  static seeAlso = ["import jobs", "projects create", "versions create", "docs errors", "tenants use"];

  static args = {
    path: Args.string({
      description: "Path to the spec file, or `-` to read raw bytes from stdin.",
      required: true,
    }),
  };

  static flags = {
    "map-project": Flags.string({
      description:
        "Target an existing catalog project by slug (tenant-scoped lookup); forwards metadata.existing_project_id. Mutually exclusive with --create-project, --create-or-map-project, and --existing-project-id.",
      exclusive: ["create-project", "create-or-map-project", "existing-project-id"],
    }),
    "create-project": Flags.boolean({
      description:
        "POST /v1/projects/{tenant} when --project-slug is free, then import onto that project id. Refuses if the slug already exists.",
      default: false,
      exclusive: ["map-project", "create-or-map-project", "existing-project-id"],
    }),
    "create-or-map-project": Flags.boolean({
      description:
        "Resolve project by slug: reuse when metadata matches; otherwise create then import (CI-friendly). Mutually exclusive with --map-project and --create-project.",
      default: false,
      exclusive: ["map-project", "create-project", "existing-project-id"],
    }),
    "project-name": Flags.string({
      description:
        "Display name for the catalog project. With --create-or-map-project, defaults to info.title from OpenAPI/AsyncAPI. Otherwise required except with --map-project (optional there for validation only).",
    }),
    "project-slug": Flags.string({
      description:
        "URL-safe project slug (^[a-z][a-z0-9-]{1,62}$). With --create-or-map-project, derived from the display name when omitted. Otherwise required unless --map-project supplies the slug.",
    }),
    version: Flags.string({
      description:
        "Catalog revision version id (prefer SemVer 2.0). With --create-or-map-project, defaults to info.version from OpenAPI/AsyncAPI when omitted. Required for other project strategies. Without --strict, invalid strict semver is normalized or forwarded with a warning.",
    }),
    "project-description": Flags.string({
      description: "Optional project description forwarded in import metadata.",
    }),
    "version-description": Flags.string({
      description: "Optional version description forwarded in import metadata.",
    }),
    "existing-project-id": Flags.string({
      description:
        "Legacy: attach the job to this catalog project id. Cannot be combined with --map-project / --create-project / --create-or-map-project.",
      exclusive: ["map-project", "create-project", "create-or-map-project"],
    }),
    domain: Flags.string({
      description:
        "Optional domainCategory when creating a project (only with --create-project or --create-or-map-project).",
    }),
    visibility: Flags.string({
      description:
        "Optional visibility metadata when creating a project: private or public (default: private).",
      options: ["private", "public"],
    }),
    yes: Flags.boolean({
      description:
        "Non-interactive guard for CI scripts (recommended with create-if-missing flags; import itself does not prompt).",
      default: false,
    }),
    format: Flags.string({
      description:
        "Importer kind when extension/content sniff is ambiguous (openapi-3, asyncapi-2, protobuf, graphql, …).",
    }),
    filename: Flags.string({
      description:
        "Original filename hint when PATH is `-` (improves sniffing for stdin payloads); may include directories (basename is used).",
    }),
    strict: Flags.boolean({
      description:
        "Require catalog version ids (--version or spec info.version) to satisfy strict SemVer 2.0 parsing. Without this flag, loose semver is normalized when possible and non-semver labels are forwarded with a warning.",
      default: false,
    }),
    "dry-run": Flags.boolean({
      description:
        "Forward dry_run in import options (validate/analyze without persisting; server-defined).",
      default: false,
    }),
    "no-wait": Flags.boolean({
      description:
        "Start the job and print the job id immediately without polling or finalize calls (CI stitching).",
      default: false,
    }),
    poll: Flags.integer({
      description:
        "Milliseconds between GET status polls while the import job is non-terminal (50–120000; default 400). Ignored with --no-wait.",
      min: 50,
      max: 120_000,
    }),
    commit: Flags.boolean({
      description:
        "After preview (pending-approval), POST …/commit (default). Use --no-commit to leave the preview transaction open.",
      default: true,
      allowNo: true,
    }),
    rollback: Flags.boolean({
      description:
        "After preview (pending-approval), POST …/rollback instead of commit (implies --no-commit).",
      default: false,
    }),
    publish: Flags.string({
      description:
        "After the import finishes successfully (saved revision, final state completed), publish that revision with public or private visibility. POST …/publish uses skipPublishChecks so server gates (class descriptions, OpenAPI materialization, baseline compatibility) do not block — verify the catalog yourself; the CLI warns after success. Ignored with --no-wait, dry-run, or when stopping before commit. Sends shortMessage via --publish-message, else first line of --version-description, else a default.",
      options: ["public", "private"],
    }),
    "publish-message": Flags.string({
      description:
        "Revision note (shortMessage) for POST …/publish when using --publish; max 500 characters. Overrides the default and --version-description.",
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
        hint: "Run `objectified tenants use <slug>` to save a default tenant.",
      });
    }

    this.ensureAuthenticated();
    this.importProgressReset();
    this.importProgress(
      `Ready to import: authenticated for tenant "${tenant}" against REST base URL ${this.context.baseUrl}`,
    );

    const pathArg = typeof this.commandArgs.path === "string" ? this.commandArgs.path : "";

    const mapRaw = typeof this.flags["map-project"] === "string" ? this.flags["map-project"].trim() : "";
    if (typeof this.flags["map-project"] === "string" && mapRaw === "") {
      throw new ObjectifiedCliError({
        message: "--map-project requires a non-empty slug value.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Pass a project slug, e.g. --map-project payments-api",
      });
    }
    const hasMap = mapRaw !== "";
    const createProject = this.flags["create-project"] === true;
    const createOrMap = this.flags["create-or-map-project"] === true;

    const existingRaw = this.flags["existing-project-id"];
    const existingTrim =
      typeof existingRaw === "string" && existingRaw.trim() !== "" ? existingRaw.trim() : undefined;

    throwIfConflictingImportProjectFlags({
      mapProjectRaw: hasMap ? mapRaw : undefined,
      createProject,
      createOrMapProject: createOrMap,
      existingProjectId: existingTrim,
    });
    this.importProgress(
      "Validated project targeting flags (--map-project, --create-project, --create-or-map-project, and --existing-project-id are mutually exclusive where required).",
    );

    const domainRaw = typeof this.flags.domain === "string" ? this.flags.domain.trim() : "";
    const domainCli = domainRaw !== "" ? domainRaw : undefined;
    const domainProvided = typeof this.flags.domain === "string";

    const visibilityRaw =
      typeof this.flags.visibility === "string" ? this.flags.visibility.trim() : "";
    const visibilityProvided = typeof this.flags.visibility === "string";
    const strictSemver = this.flags.strict === true;
    let visibilityCli: Visibility | undefined;
    if (visibilityProvided) {
      if (visibilityRaw !== "private" && visibilityRaw !== "public") {
        throw new ObjectifiedCliError({
          message: "--visibility must be private or public.",
          exitCode: EXIT_CODES.MISUSE,
          title: "Invalid usage",
        });
      }
      visibilityCli = visibilityRaw as Visibility;
    }

    if (domainProvided || visibilityProvided) {
      if (!createProject && !createOrMap) {
        throw new ObjectifiedCliError({
          message:
            "--domain and --visibility are only valid with --create-project or --create-or-map-project.",
          exitCode: EXIT_CODES.MISUSE,
          title: "Invalid usage",
        });
      }
    }

    const projectNameRaw = this.flags["project-name"];
    const projectName = typeof projectNameRaw === "string" ? projectNameRaw.trim() : "";
    const projectSlugRaw = this.flags["project-slug"];
    const versionRaw = typeof this.flags.version === "string" ? this.flags.version.trim() : "";

    if (!createOrMap && versionRaw === "") {
      throw new ObjectifiedCliError({
        message: "--version is required unless --create-or-map-project derives it from the spec.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
      });
    }

    const projDescRaw = this.flags["project-description"];
    const descriptionProvided = typeof projDescRaw === "string";
    const projectDescriptionForTarget =
      typeof projDescRaw === "string" && projDescRaw.trim() !== "" ? projDescRaw.trim() : null;

    if (hasMap && descriptionProvided) {
      throw new ObjectifiedCliError({
        message:
          "--project-description cannot be used with --map-project (the existing project's description is used).",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Remove --project-description or use --create-project / --create-or-map-project instead.",
      });
    }

    const formatRaw = typeof this.flags.format === "string" ? this.flags.format.trim() : "";
    const explicitFormat = formatRaw !== "" ? formatRaw : undefined;

    const stdinFilenameRaw =
      typeof this.flags.filename === "string" ? this.flags.filename.trim() : "";
    const stdinFilename = stdinFilenameRaw !== "" ? stdinFilenameRaw : undefined;

    let resolved: ResolvedSpecImportProject;
    let versionId: string;
    let bytes: Buffer;
    let resolvedPath: string;
    let kind: ResolvedSpecKind;

    if (hasMap) {
      const mapVer = resolveImportCatalogVersionId(versionRaw, strictSemver);
      versionId = mapVer.versionId;
      this.emitImportSemverWarnings(mapVer.semverWarnings);
      this.importProgress(
        `Resolving --map-project: looking up existing catalog project with slug "${mapRaw}" in this tenant (GET project by slug).`,
      );
      resolved = await resolveMapProjectImport({
        api: this.api,
        tenant,
        mapSlugRaw: mapRaw,
        cliProjectName: projectName !== "" ? projectName : undefined,
        cliProjectSlug:
          typeof projectSlugRaw === "string" && projectSlugRaw.trim() !== ""
            ? projectSlugRaw
            : undefined,
      });
      this.importProgress(
        `Reading specification document from ${pathArg === "-" ? "standard input" : `file ${pathArg}`}.`,
      );
      ({ bytes, resolvedPath } = await readSpecInput(pathArg));
      kind = resolveSpecImportKind({
        explicitFormat,
        stdinFilename,
        resolvedPath,
        bytes,
      });
      this.importProgress(
        `Detected importer format "${kind.sourceKind}" from contents and filename (${String(bytes.length)} bytes).`,
      );
    } else if (createOrMap) {
      this.importProgress(
        `Reading specification document from ${pathArg === "-" ? "standard input" : `file ${pathArg}`}.`,
      );
      ({ bytes, resolvedPath } = await readSpecInput(pathArg));
      kind = resolveSpecImportKind({
        explicitFormat,
        stdinFilename,
        resolvedPath,
        bytes,
      });
      this.importProgress(
        `Detected importer format "${kind.sourceKind}" from contents and filename (${String(bytes.length)} bytes).`,
      );
      const derived = deriveCatalogIdentityFromSpecBytes(bytes, kind.sourceKind);
      const catalogIdentity = resolveCatalogIdentityForCreateOrMap({
        derived,
        sourceKind: kind.sourceKind,
        cliProjectName: projectName,
        cliProjectSlug: typeof projectSlugRaw === "string" ? projectSlugRaw.trim() : "",
        cliVersionRaw: versionRaw,
        strictSemver,
      });
      versionId = catalogIdentity.versionId;
      this.emitImportSemverWarnings(catalogIdentity.semverWarnings);
      const projectTarget = {
        name: catalogIdentity.projectName,
        slug: catalogIdentity.projectSlug,
        description: projectDescriptionForTarget,
      };
      this.importProgress(
        `Derived catalog identity from the spec and CLI flags: project slug "${catalogIdentity.projectSlug}", catalog version id "${catalogIdentity.versionId}".`,
      );
      this.importProgress(
        "Resolving --create-or-map-project: reuse existing project when slug and metadata match, otherwise create a new project (GET then possibly POST /v1/projects).",
      );
      resolved = await resolveCreateOrMapProjectImport({
        api: this.api,
        tenant,
        project: projectTarget,
        hints: {
          descriptionProvided,
          domainProvided,
          visibilityProvided,
        },
        domain: domainCli,
        visibility: visibilityCli,
      });
    } else if (createProject) {
      const cpVer = resolveImportCatalogVersionId(versionRaw, strictSemver);
      versionId = cpVer.versionId;
      this.emitImportSemverWarnings(cpVer.semverWarnings);
      if (projectName === "") {
        throw new ObjectifiedCliError({
          message: "--project-name is required with --create-project.",
          exitCode: EXIT_CODES.MISUSE,
          title: "Invalid usage",
        });
      }
      const slugCheckCreate = validateProjectSlug(
        typeof projectSlugRaw === "string" ? projectSlugRaw : "",
      );
      if (!slugCheckCreate.ok) {
        throw new ObjectifiedCliError({
          message: slugCheckCreate.message,
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint:
            slugCheckCreate.suggestion !== undefined
              ? `Try slug ${slugCheckCreate.suggestion}`
              : undefined,
        });
      }
      const projectTarget = {
        name: projectName,
        slug: slugCheckCreate.slug,
        description: projectDescriptionForTarget,
      };
      this.importProgress(
        `Creating a new catalog project with slug "${slugCheckCreate.slug}" (POST /v1/projects for this tenant).`,
      );
      resolved = await resolveCreateProjectImport({
        api: this.api,
        tenant,
        project: projectTarget,
        domain: domainCli,
        visibility: visibilityCli,
      });
      this.importProgress(
        `Reading specification document from ${pathArg === "-" ? "standard input" : `file ${pathArg}`}.`,
      );
      ({ bytes, resolvedPath } = await readSpecInput(pathArg));
      kind = resolveSpecImportKind({
        explicitFormat,
        stdinFilename,
        resolvedPath,
        bytes,
      });
      this.importProgress(
        `Detected importer format "${kind.sourceKind}" from contents and filename (${String(bytes.length)} bytes).`,
      );
    } else {
      const legVer = resolveImportCatalogVersionId(versionRaw, strictSemver);
      versionId = legVer.versionId;
      this.emitImportSemverWarnings(legVer.semverWarnings);
      if (projectName === "") {
        throw new ObjectifiedCliError({
          message: "--project-name is required unless --map-project is set.",
          exitCode: EXIT_CODES.MISUSE,
          title: "Invalid usage",
        });
      }
      const slugCheckLegacy = validateProjectSlug(
        typeof projectSlugRaw === "string" ? projectSlugRaw : "",
      );
      if (!slugCheckLegacy.ok) {
        throw new ObjectifiedCliError({
          message: slugCheckLegacy.message,
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint:
            slugCheckLegacy.suggestion !== undefined
              ? `Try slug ${slugCheckLegacy.suggestion}`
              : undefined,
        });
      }
      resolved = {
        existingProjectId: existingTrim ?? null,
        project: {
          name: projectName,
          slug: slugCheckLegacy.slug,
          description: projectDescriptionForTarget,
        },
      };
      this.importProgress(
        `Using CLI-supplied project metadata only (slug "${slugCheckLegacy.slug}"${existingTrim !== undefined ? `; attaching to existing_project_id=${existingTrim}` : "; existing_project_id will be chosen by the server if omitted"}).`,
      );
      this.importProgress(
        `Reading specification document from ${pathArg === "-" ? "standard input" : `file ${pathArg}`}.`,
      );
      ({ bytes, resolvedPath } = await readSpecInput(pathArg));
      kind = resolveSpecImportKind({
        explicitFormat,
        stdinFilename,
        resolvedPath,
        bytes,
      });
      this.importProgress(
        `Detected importer format "${kind.sourceKind}" from contents and filename (${String(bytes.length)} bytes).`,
      );
    }

    const projectStrategy = hasMap
      ? "map-project"
      : createOrMap
        ? "create-or-map-project"
        : createProject
          ? "create-project"
          : "metadata-only";
    this.importProgress(
      `Project targeting complete (strategy "${projectStrategy}"): catalog project "${resolved.project.name}" (slug "${resolved.project.slug}")${resolved.existingProjectId !== null && resolved.existingProjectId !== "" ? `, catalog_project_id=${resolved.existingProjectId}` : ", catalog_project_id to be assigned by the importer"}.`,
    );
    this.importProgress(
      `Specification source resolved to "${resolvedPath}"; this revision will be imported as catalog version id "${versionId}".`,
    );

    const extractedSpecInfo = extractSpecInfoForCliDisplay(bytes, kind.sourceKind);
    this.logExtractedSpecificationSummary({
      extracted: extractedSpecInfo,
      sourceKind: kind.sourceKind,
      resolved,
      catalogVersionId: versionId,
      resolvedPath,
    });

    const rollback = this.flags.rollback === true;
    const commit = !rollback && this.flags.commit !== false;

    const dryRun = this.flags["dry-run"] === true;
    const noWait = this.flags["no-wait"] === true;
    const pollIntervalMs = typeof this.flags.poll === "number" ? this.flags.poll : undefined;
    if (pollIntervalMs !== undefined && noWait) {
      this.warn("--poll is ignored with --no-wait (this run does not poll).");
    }
    const publishIntent = this.parsePublishVisibilityIntent();

    const verDescRaw = this.flags["version-description"];

    const documentBase64 = bytes.toString("base64");

    this.importProgress(
      `Submitting import job: POST /v1/tenants/${tenant}/imports with the specification as base64 (${String(documentBase64.length)} encoded characters)${dryRun ? "; dry_run=true (server validates without persisting per API contract)" : ""}${noWait ? "; --no-wait will return as soon as the job is accepted" : ""}.`,
    );

    const accepted: SpecImportJobAccepted = await this.api.startSpecImportJson(tenant, {
      metadata: {
        source_kind: kind.sourceKind,
        project: resolved.project,
        version: {
          version_id: versionId,
          description:
            typeof verDescRaw === "string" && verDescRaw.trim() !== "" ? verDescRaw.trim() : null,
        },
        existing_project_id: resolved.existingProjectId ?? null,
        options: dryRun ? { dry_run: true } : undefined,
      },
      document_base64: documentBase64,
      filename: kind.filenameForRequest ?? undefined,
      content_type: kind.contentType ?? undefined,
    });

    this.importProgress(
      `Import job accepted by the server: job_id=${accepted.job_id} — poll status with GET ${accepted.status_path}.`,
    );

    if (noWait) {
      if (publishIntent !== undefined) {
        this.warn("--publish is ignored with --no-wait (this run does not wait for import completion).");
      }
      this.importProgress(
        "--no-wait: not polling job status and not sending commit or rollback — finish the workflow via the API or `objectified import jobs` when ready.",
      );
      const early: ImportSpecSummaryJson = {
        tenant_slug: tenant,
        job_id: accepted.job_id,
        status_path: accepted.status_path,
        final_state: "queued",
        source_kind: kind.sourceKind,
        stopped_at: null,
      };
      if (this.context.json) {
        this.output.json(early);
      } else {
        this.output.table(
          [
            {
              job_id: accepted.job_id,
              status_path: accepted.status_path,
              tenant_slug: tenant,
              source_kind: kind.sourceKind,
            },
          ],
          [
            { key: "job_id", label: "Job" },
            { key: "status_path", label: "Status path" },
            { key: "tenant_slug", label: "Tenant" },
            { key: "source_kind", label: "Kind" },
          ],
        );
      }
      this.importProgress(
        "Finished CLI run with final_state=queued (--no-wait): use the printed status_path or job_id to monitor and finalize the import separately.",
      );
      return;
    }

    const pollLog = this.flags.quiet !== true
      ? (line: string): void => {
          if (line.startsWith("Waiting ") && !this.verboseEffective) return;
          this.importProgress(line);
        }
      : undefined;
    this.importProgress(
      `Polling import job status via GET ${accepted.status_path} until the job reaches pending-approval (preview ready), completed, failed, canceled, or rolled-back.`,
    );

    let commitOut: SpecImportCommitResponse | undefined;
    let rollbackOut: SpecImportRollbackResponse | undefined;

    let st = await pollSpecImportUntilGate({
      api: this.api,
      tenantSlug: tenant,
      jobId: accepted.job_id,
      log: pollLog,
      pollIntervalMs,
    });

    if (st.state === "failed" || st.state === "canceled") {
      throwForBadTerminalState(st);
    }

    if (st.state === "rolled-back") {
      throwForBadTerminalState(st);
    }

    if (st.state === "completed") {
      this.importProgress(
        "Import reached completed without a pending-approval pause — the catalog revision is already finalized on the server (no commit POST needed for this job).",
      );
      const summary = this.buildSummaryJson({
        tenant,
        accepted,
        kindSource: kind.sourceKind,
        final: st,
        commit: undefined,
        rollback: undefined,
        stoppedAt: null,
      });
      await this.maybePublishImportedRevision(tenant, summary, dryRun);
      this.emitSummary(summary);
      this.importProgress(`Import command finished successfully (final_state=${summary.final_state}).`);
      return;
    }

    if (st.state === "pending-approval") {
      this.importProgress(
        `Import preview is ready (pending-approval): commit=${String(commit)} rollback=${String(rollback)} — the server holds a transaction open until you commit, rollback, or exit with --no-commit.`,
      );
      if (!commit && !rollback) {
        if (publishIntent !== undefined) {
          this.warn(
            "--publish is ignored when stopping at pending-approval without commit (no saved revision to publish).",
          );
        }
        this.importProgress(
          "Stopping at pending-approval per --no-commit: no commit or rollback POST will be sent; finalize later via the REST API when you are satisfied with the preview.",
        );
        const summary = this.buildSummaryJson({
          tenant,
          accepted,
          kindSource: kind.sourceKind,
          final: st,
          commit: undefined,
          rollback: undefined,
          stoppedAt: "pending-approval",
        });
        this.emitSummary(summary);
        this.importProgress(
          `Import command exiting after preview (final_state=${summary.final_state}); commit or rollback via the API when ready.`,
        );
        return;
      }

      if (rollback) {
        this.importProgress(
          `Discarding the preview: POST /v1/tenants/${tenant}/imports/${accepted.job_id}/rollback (drops the staged catalog changes).`,
        );
        rollbackOut = await this.api.rollbackSpecImportJob(tenant, accepted.job_id);
      } else {
        this.importProgress(
          `Persisting the preview: POST /v1/tenants/${tenant}/imports/${accepted.job_id}/commit (writes the staged catalog revision).`,
        );
        commitOut = await this.api.commitSpecImportJob(tenant, accepted.job_id);
      }

      this.importProgress(
        "Polling import status again until the job reaches a terminal state (completed, failed, canceled, or rolled-back) after commit or rollback.",
      );
      st = await pollSpecImportUntilTerminal({
        api: this.api,
        tenantSlug: tenant,
        jobId: accepted.job_id,
        log: pollLog,
        pollIntervalMs,
      });

      if (st.state === "failed" || st.state === "canceled") {
        throwForBadTerminalState(st);
      }
      if (st.state === "rolled-back" && rollbackOut === undefined) {
        throwForBadTerminalState(st);
      }
    }

    this.importProgress(`Import lifecycle finished with terminal state "${st.state}".`);
    const summary = this.buildSummaryJson({
      tenant,
      accepted,
      kindSource: kind.sourceKind,
      final: st,
      commit: commitOut ?? null,
      rollback: rollbackOut ?? null,
      stoppedAt: null,
    });
    await this.maybePublishImportedRevision(tenant, summary, dryRun);
    this.emitSummary(summary);
    this.importProgress(`Import command finished successfully (final_state=${summary.final_state}).`);
  }

  /** Sequential counter so stderr lines stay ordered per invocation. */
  private importProgressSeq = 0;

  private importProgressReset(): void {
    this.importProgressSeq = 0;
  }

  /**
   * Import milestones and poll snapshots on stderr (`objectified: import: [n] …`).
   * Suppressed by `--quiet`. Does not change stdout or `--json` payloads.
   */
  private importProgress(message: string): void {
    if (this.flags.quiet === true) return;
    this.importProgressSeq++;
    process.stderr.write(`objectified: import: [${String(this.importProgressSeq)}] ${message}\n`);
  }

  /** SemVer mismatch warnings (non-strict); suppressed when --quiet. */
  private emitImportSemverWarnings(warnings: string[]): void {
    if (this.flags.quiet === true || warnings.length === 0) return;
    for (const w of warnings) {
      this.warn(w);
    }
  }

  private parsePublishVisibilityIntent(): "public" | "private" | undefined {
    const raw = this.flags.publish;
    if (typeof raw !== "string") return undefined;
    const v = raw.trim().toLowerCase();
    return v === "public" || v === "private" ? v : undefined;
  }

  /** API requires shortMessage on publish; align with `versions publish --message`. */
  private resolvePublishShortMessage(): string {
    const pubMsg = this.flags["publish-message"];
    if (typeof pubMsg === "string" && pubMsg.trim() !== "") {
      return pubMsg.trim().slice(0, 500);
    }
    const verDesc = this.flags["version-description"];
    if (typeof verDesc === "string" && verDesc.trim() !== "") {
      const firstLine = verDesc.trim().split(/\r?\n/)[0]?.trim() ?? "";
      if (firstLine !== "") return firstLine.slice(0, 500);
    }
    return "Published after specification import";
  }

  /**
   * POST …/publish after a successful import (`final_state` completed, revision ids present).
   * No-op when `--publish` omitted; warns when publish cannot apply (dry-run, wrong terminal state).
   */
  private async maybePublishImportedRevision(
    tenant: string,
    summary: ImportSpecSummaryJson,
    dryRun: boolean,
  ): Promise<void> {
    const visibility = this.parsePublishVisibilityIntent();
    if (visibility === undefined) return;

    if (dryRun) {
      this.warn(`--publish=${visibility} ignored: dry-run imports do not persist a catalog revision.`);
      return;
    }

    if (summary.final_state !== "completed") {
      this.warn(
        `--publish=${visibility} ignored: import did not complete successfully (final_state=${summary.final_state}).`,
      );
      return;
    }

    const projectId = summary.project_id?.trim();
    const versionRecordId = summary.version_record_id?.trim();
    if (!projectId || !versionRecordId) {
      throw new ObjectifiedCliError({
        message: "Cannot publish: import result is missing project_id or version_record_id.",
        exitCode: EXIT_CODES.GENERIC,
        title: "Publish failed",
        hint: "Import reported success but no revision identifiers were returned; inspect job status or retry without --no-wait.",
      });
    }

    const shortMessage = this.resolvePublishShortMessage();
    this.importProgress(
      `Publishing the saved revision: POST …/publish for version_record_id=${versionRecordId} with visibility=${visibility} (skipPublishChecks=true per CLI contract — server publication gates are not enforced).`,
    );
    const body: VersionPublishRequest = {
      visibility,
      shortMessage,
      changeReportBaselineMode: "auto",
      skipPublishChecks: true,
    };
    try {
      const published = await this.api.publishVersion(tenant, projectId, versionRecordId, body);
      summary.publish = {
        visibility,
        published: true,
        version_record_id: published.id,
      };
      this.warn(
        "Published without server publication gates (class descriptions, OpenAPI build, baseline compatibility were not enforced). Review the revision before sharing.",
      );
    } catch (e: unknown) {
      if (e instanceof ObjectifiedCliError) {
        const followUp =
          "Import saved the revision; run `objectified versions publish …` if you need gated publication, or retry import with `--publish`.";
        throw new ObjectifiedCliError({
          message: `Import finished but publish failed: ${e.message}`,
          exitCode: e.exitCode,
          title: "Publish failed",
          hint: e.hint !== undefined && e.hint !== "" ? `${e.hint} ${followUp}` : followUp,
          requestId: e.requestId,
          retriesAttempted: e.retriesAttempted,
        });
      }
      throw e;
    }
  }

  /**
   * OpenAPI/AsyncAPI: prints spec `info` (title, version, description, other fields).
   * Other kinds: notes that no `info` block is available. Uses stderr; suppressed by `--quiet`.
   */
  private logExtractedSpecificationSummary(opts: {
    extracted: ReturnType<typeof extractSpecInfoForCliDisplay>;
    sourceKind: string;
    resolved: ResolvedSpecImportProject;
    catalogVersionId: string;
    resolvedPath: string;
  }): void {
    if (this.flags.quiet === true) return;
    const { extracted, sourceKind, resolved, catalogVersionId, resolvedPath } = opts;
    const label = path.basename(resolvedPath);
    this.importProgress(
      `Specification summary for this run (file "${label}", importer kind "${sourceKind}"):`,
    );
    this.importProgress(`  catalog project name: ${resolved.project.name}`);
    this.importProgress(`  catalog project slug: ${resolved.project.slug}`);
    this.importProgress(`  catalog version id: ${catalogVersionId}`);
    const cliProjDesc = resolved.project.description;
    if (typeof cliProjDesc === "string" && cliProjDesc.trim() !== "") {
      this.importProgress(`  catalog project description (from CLI): ${cliProjDesc.trim()}`);
    }

    if (extracted === null) {
      this.importProgress(
        `  spec info: (no structured info block for this format; title/description/metadata apply to OpenAPI and AsyncAPI)`,
      );
      return;
    }

    this.importProgress(`  spec title (info.title): ${extracted.title ?? "(not set)"}`);
    this.importProgress(`  spec version (info.version): ${extracted.version ?? "(not set)"}`);

    if (extracted.description !== undefined) {
      const maxLines = 24;
      const maxChars = 4000;
      let body = extracted.description;
      if (body.length > maxChars) {
        body = `${body.slice(0, maxChars)}…`;
      }
      const lines = body.split(/\r?\n/);
      const clipped = lines.slice(0, maxLines);
      for (let i = 0; i < clipped.length; i++) {
        const prefix = i === 0 ? "  spec description (info.description): " : "    ";
        const line = clipped[i] ?? "";
        this.importProgress(`${prefix}${line}`);
      }
      if (lines.length > maxLines) {
        this.importProgress(`    … (${String(lines.length - maxLines)} more line(s) omitted)`);
      }
    } else {
      this.importProgress(`  spec description (info.description): (not set)`);
    }

    const metaKeys = Object.keys(extracted.infoMetadata);
    if (metaKeys.length === 0) {
      this.importProgress(`  spec metadata (other info.* fields): (none)`);
    } else {
      try {
        const json = JSON.stringify(extracted.infoMetadata);
        this.importProgress(`  spec metadata (other info.* fields): ${json}`);
      } catch {
        this.importProgress(`  spec metadata (other info.* fields): (present but not JSON-serializable)`);
      }
    }
  }

  private buildSummaryJson(opts: {
    tenant: string;
    accepted: SpecImportJobAccepted;
    kindSource: string;
    final: SpecImportJobStatus;
    commit?: SpecImportCommitResponse | null;
    rollback?: SpecImportRollbackResponse | null;
    stoppedAt: "pending-approval" | null;
  }): ImportSpecSummaryJson {
    const r = opts.final.result ?? undefined;
    const projSlug = opts.commit?.project_slug ?? r?.project_slug ?? null;
    const projId = opts.commit?.project_id ?? r?.project_id ?? null;
    const verId = opts.commit?.version_id ?? r?.version_id ?? null;
    const verRec = opts.commit?.version_record_id ?? r?.version_record_id ?? null;
    return {
      tenant_slug: opts.tenant,
      job_id: opts.final.job_id,
      status_path: opts.accepted.status_path,
      final_state: opts.final.state,
      source_kind: opts.kindSource,
      project_slug: projSlug,
      project_id: projId,
      version_id: verId,
      version_record_id: verRec,
      summary:
        opts.final.summary !== undefined &&
        opts.final.summary !== null &&
        typeof opts.final.summary === "object"
          ? (opts.final.summary as Record<string, unknown>)
          : opts.final.summary === null
            ? null
            : undefined,
      commit: opts.commit ?? null,
      rollback: opts.rollback ?? null,
      stopped_at: opts.stoppedAt,
    };
  }

  private emitSummary(summary: ImportSpecSummaryJson): void {
    if (this.context.json) {
      this.output.json(summary);
      return;
    }

    const publishCell =
      summary.publish !== undefined && summary.publish !== null
        ? `${summary.publish.visibility} (published)`
        : "";

    const rows: Record<string, unknown>[] = [
      {
        job_id: summary.job_id,
        state: summary.final_state,
        tenant_slug: summary.tenant_slug,
        source_kind: summary.source_kind,
        project_slug: summary.project_slug ?? "",
        project_id: summary.project_id ?? "",
        version_id: summary.version_id ?? "",
        version_record_id: summary.version_record_id ?? "",
        publish: publishCell,
      },
    ];

    this.output.table(rows, [
      { key: "job_id", label: "Job" },
      { key: "state", label: "State" },
      { key: "tenant_slug", label: "Tenant" },
      { key: "source_kind", label: "Kind" },
      { key: "project_slug", label: "Project slug" },
      { key: "project_id", label: "Project id" },
      { key: "version_id", label: "Version" },
      { key: "version_record_id", label: "Revision id" },
      { key: "publish", label: "Publish" },
    ]);

    if (summary.stopped_at === "pending-approval") {
      this.output.warn(
        "Import stopped at pending-approval (--no-commit). Commit or rollback later via the REST API.",
      );
    }

    if (summary.summary !== undefined && summary.summary !== null) {
      this.output.text(`Summary: ${JSON.stringify(summary.summary)}`);
    }
  }
}
