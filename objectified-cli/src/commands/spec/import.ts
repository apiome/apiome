import fs from "node:fs";
import path from "node:path";

import { Args, Flags } from "@oclif/core";
import YAML from "yaml";

import { BaseCommand } from "../../base-command.js";
import type {
  ImportJobResponse,
  ImportSourceKind,
  ObjectifiedApi,
  ProjectSchema,
} from "../../lib/client.js";
import { ObjectifiedCliError } from "../../lib/errors.js";
import { EXIT_CODES } from "../../lib/exit-codes.js";
import { localePrefersAsciiTable } from "../../lib/output.js";
import { PROJECT_DOMAIN_CATEGORY_NONE } from "../../lib/projects/domain-categories.js";
import type { Visibility } from "../../lib/projects/project-create-body.js";
import { buildProjectCreateRequest } from "../../lib/projects/project-create-body.js";
import { validateProjectSlug } from "../../lib/projects/project-slug.js";
import { completionProfileCacheKey, resolveProjectForTenant } from "../../lib/resolve.js";
import {
  metadataRecordFromSpecDraft,
  projectDraftFromSpecContent,
  suggestProjectSlugFromSpec,
  type SpecProjectDraft,
} from "../../lib/spec/project-draft-from-spec.js";

const SOURCE_FLAG_OPTIONS = ["openapi", "swagger", "arazzo", "auto"] as const;

type SourceFlag = (typeof SOURCE_FLAG_OPTIONS)[number];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pickStr(o: Record<string, unknown>, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === "string") {
      const t = v.trim();
      if (t !== "") return t;
    }
  }
  return undefined;
}

function loadStructuredSpecFile(filePath: string): { raw: string; parsed: unknown } {
  const abs = path.resolve(process.cwd(), filePath);
  if (!fs.existsSync(abs)) {
    throw new ObjectifiedCliError({
      message: `Spec file not found: ${abs}`,
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid usage",
      hint: "Pass a path to an existing OpenAPI, Swagger, or Arazzo document.",
    });
  }
  const raw = fs.readFileSync(abs, "utf8");
  const lower = abs.toLowerCase();
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) {
    try {
      return { raw, parsed: YAML.parse(raw) as unknown };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new ObjectifiedCliError({
        message: `Invalid YAML in spec file: ${msg}`,
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Fix the YAML syntax or use .json for JSON.",
      });
    }
  }
  try {
    return { raw, parsed: JSON.parse(raw) as unknown };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new ObjectifiedCliError({
      message: `Invalid JSON in spec file: ${msg}`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Fix the JSON syntax or use .yaml / .yml for YAML.",
    });
  }
}

function normalizeDomainCategory(raw: string | undefined): string | undefined {
  if (raw === undefined) return undefined;
  const t = raw.trim();
  if (t === "" || t === PROJECT_DOMAIN_CATEGORY_NONE) return undefined;
  return t;
}

function loadImportOptionsJson(filePath: string): Record<string, unknown> {
  const abs = path.resolve(process.cwd(), filePath);
  if (!fs.existsSync(abs)) {
    throw new ObjectifiedCliError({
      message: `Import options file not found: ${abs}`,
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid usage",
      hint: "Pass a path to an existing ImportOptions JSON file.",
    });
  }
  const raw = fs.readFileSync(abs, "utf8");
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new ObjectifiedCliError({
      message: `Invalid JSON in import options file: ${msg}`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "ImportOptions must be valid JSON.",
    });
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new ObjectifiedCliError({
      message: "Import options file must contain a JSON object.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected an object with optional selectedSchemas, naming, etc.",
    });
  }
  return parsed as Record<string, unknown>;
}

function buildOptionsFromImportFile(fileDoc: Record<string, unknown>): Record<string, unknown> {
  const skip = new Set([
    "options",
    "name",
    "slug",
    "description",
    "versionId",
    "version_id",
    "versionDescription",
    "version_description",
  ]);
  const options: Record<string, unknown> = {};
  const nested = fileDoc.options;
  if (
    nested !== undefined &&
    nested !== null &&
    typeof nested === "object" &&
    !Array.isArray(nested)
  ) {
    Object.assign(options, nested as Record<string, unknown>);
  }
  for (const [k, v] of Object.entries(fileDoc)) {
    if (skip.has(k)) continue;
    options[k] = v;
  }
  return options;
}

function detectSourceKind(doc: unknown, override: SourceFlag): ImportSourceKind {
  if (override !== "auto") {
    return override;
  }
  if (doc === null || typeof doc !== "object" || Array.isArray(doc)) {
    throw new ObjectifiedCliError({
      message: "Spec document must be a JSON or YAML object at the root.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Pass a valid OpenAPI 3.x, Swagger 2.0, or Arazzo 1.x document.",
    });
  }
  const o = doc as Record<string, unknown>;
  if ("arazzo" in o) return "arazzo";
  if ("openapi" in o) return "openapi";
  if ("swagger" in o) return "swagger";
  throw new ObjectifiedCliError({
    message:
      "Could not detect spec format (expected top-level openapi, swagger, or arazzo key). Use --source to override.",
    exitCode: EXIT_CODES.VALIDATION,
    title: "Validation failed",
    hint: "Try `--source openapi`, `--source swagger`, or `--source arazzo`.",
  });
}

function formatDetectedLine(kind: ImportSourceKind, doc: Record<string, unknown>): string {
  const infoRaw = doc.info;
  const info =
    infoRaw !== undefined &&
    infoRaw !== null &&
    typeof infoRaw === "object" &&
    !Array.isArray(infoRaw)
      ? (infoRaw as Record<string, unknown>)
      : undefined;
  const title = info !== undefined && typeof info.title === "string" ? info.title : "?";
  const ver = info !== undefined && typeof info.version === "string" ? info.version : "?";

  if (kind === "openapi") {
    const ov = typeof doc.openapi === "string" ? doc.openapi : "?";
    return `OpenAPI ${ov} (info.title='${title}', info.version='${ver}')`;
  }
  if (kind === "swagger") {
    const sv = typeof doc.swagger === "string" ? doc.swagger : "?";
    return `Swagger ${sv} (info.title='${title}', info.version='${ver}')`;
  }
  const av = typeof doc.arazzo === "string" ? doc.arazzo : "?";
  return `Arazzo ${av} (info.title='${title}', info.version='${ver}')`;
}

function extractVersionMeta(doc: Record<string, unknown>): {
  versionId: string;
  description: string | null;
} {
  const infoRaw = doc.info;
  const info =
    infoRaw !== undefined &&
    infoRaw !== null &&
    typeof infoRaw === "object" &&
    !Array.isArray(infoRaw)
      ? (infoRaw as Record<string, unknown>)
      : undefined;
  const versionId =
    info !== undefined && typeof info.version === "string" && info.version.trim() !== ""
      ? info.version.trim()
      : "";
  if (versionId === "") {
    throw new ObjectifiedCliError({
      message: "Spec is missing info.version (needed for the import revision label).",
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid usage",
      hint: "Add `info.version` to the document or extend ImportOptions (future CLI flags may map here).",
    });
  }
  const description =
    info !== undefined && typeof info.description === "string" && info.description.trim() !== ""
      ? info.description.trim()
      : null;
  return { versionId, description };
}

function progressSpinnerText(job: ImportJobResponse): string {
  const p = job.progress;
  if (p === undefined || p === null) {
    return `Importing… (${job.state})`;
  }
  const phase = p.phase.trim() !== "" ? p.phase : "working";
  const total = p.total;
  const done = p.completed;
  const item =
    typeof p.currentItem === "string" && p.currentItem.trim() !== ""
      ? ` ${p.currentItem.trim()}`
      : "";
  if (typeof total === "number" && typeof done === "number" && total > 0) {
    return `[${phase} ${String(done)}/${String(total)}]${item}`;
  }
  return `[${phase}]${item}`;
}

function isPollingTerminalState(state: string): boolean {
  return (
    state === "completed" ||
    state === "failed" ||
    state === "canceled" ||
    state === "rolled-back" ||
    state === "pending-approval"
  );
}

async function followImportJob(opts: {
  api: ObjectifiedApi;
  tenantSlug: string;
  initial: ImportJobResponse;
  spinnerText: (job: ImportJobResponse) => string;
  createSpinner: (text: string) => import("ora").Ora;
}): Promise<ImportJobResponse> {
  let job = opts.initial;
  const spin = opts.createSpinner(opts.spinnerText(job));
  spin.start();
  try {
    const pollEpoch = Date.now();
    let delayMs = 1000;
    while (!isPollingTerminalState(job.state)) {
      const elapsed = Date.now() - pollEpoch;
      if (elapsed >= 30_000) {
        delayMs = Math.min(5000, delayMs * 2);
      }
      await sleep(delayMs);
      job = await opts.api.getImportJob(opts.tenantSlug, job.jobId);
      spin.text = opts.spinnerText(job);
    }
    return job;
  } finally {
    spin.stop();
  }
}

function formatSummaryFollowUp(job: ImportJobResponse, projectSlug: string): string | undefined {
  const vid =
    job.result?.versionId ??
    (job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
      ? pickStr(job.summary as Record<string, unknown>, ["versionId", "version_id"])
      : undefined);
  if (vid !== undefined && vid !== "") {
    return `Run \`objectified versions show ${projectSlug} ${vid}\` to inspect.`;
  }
  return undefined;
}

function formatClassesSummary(
  summary: Record<string, unknown> | null | undefined,
): string | undefined {
  if (summary === undefined || summary === null || typeof summary !== "object") return undefined;
  const created = summary.classesCreated ?? summary.classes_created;
  const warnings = summary.warnings ?? summary.class_warnings;
  const failed = summary.failed ?? summary.classes_failed;
  if (typeof created === "number" && typeof warnings === "number" && typeof failed === "number") {
    return `Classes: ${String(created)} created, ${String(warnings)} warnings, ${String(failed)} failed.`;
  }
  return undefined;
}

export default class SpecImport extends BaseCommand {
  static description =
    "Import an OpenAPI / Swagger / Arazzo document (POST /v1/imports/{tenant_slug}). Omit --project to create a project from spec info, then import.";

  static examples = [
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --project payments-api",
    "<%= config.bin %> <%= command.id %> ./openapi.yaml --yes",
    "<%= config.bin %> <%= command.id %> ./spec.json --slug my-api --visibility public --yes",
    "<%= config.bin %> <%= command.id %> ./spec.json --project payments-api --source openapi",
    "<%= config.bin %> <%= command.id %> ./workflow.yaml --project api --from-file ./import-options.json",
    "<%= config.bin %> --json <%= command.id %> ./openapi.yaml --project payments-api",
    "<%= config.bin %> <%= command.id %> ./fixtures/petstore.yaml --project petstore --yes",
    "<%= config.bin %> <%= command.id %> ./arazzo.yaml --project checkout --source arazzo",
  ];

  static seeAlso = ["versions show", "versions list", "projects show", "docs errors"];

  static args = {
    file: Args.string({
      description: "Path to OpenAPI 3.x, Swagger 2.0, or Arazzo 1.x spec (JSON or YAML).",
      required: true,
    }),
  };

  static flags = {
    project: Flags.string({
      description:
        "Existing project slug or UUID (omit to create a project from spec info.title / info.description / contact / license, then import).",
    }),
    source: Flags.string({
      description: "Override format detection (default: auto-detect from document keys).",
      options: [...SOURCE_FLAG_OPTIONS],
      default: "auto",
    }),
    "from-file": Flags.string({
      description:
        "Merge ImportOptions JSON (selectedSchemas, naming, etc.). CLI flags override file values.",
    }),
    name: Flags.string({
      description:
        "Project display name (import body; when creating a project, also used for POST /v1/projects unless omitted).",
    }),
    slug: Flags.string({
      description:
        "Project slug (import body; when creating a project, must match ^[a-z][a-z0-9-]{1,62}$ — use another if the tenant already has this slug).",
    }),
    description: Flags.string({
      description:
        "Project description (import body; when creating a project, stored on the new project).",
    }),
    domain: Flags.string({
      description:
        "When creating a project: metadata domainCategory (same as `projects create --domain`).",
    }),
    visibility: Flags.string({
      description: "When creating a project: metadata visibility (private or public).",
      options: ["private", "public"],
    }),
    yes: Flags.boolean({
      description:
        "Skip confirmation when creating a project from the spec; required when stdin is not a TTY and --project is omitted.",
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

    const rawFileArg = this.commandArgs.file;
    const specPath = typeof rawFileArg === "string" ? rawFileArg.trim() : "";
    if (specPath === "") {
      throw new ObjectifiedCliError({
        message: "Spec file path is required.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Pass a path to a JSON or YAML document.",
      });
    }

    const rawProject = typeof this.flags.project === "string" ? this.flags.project.trim() : "";
    const createProjectFromSpec = rawProject === "";

    const sourceRaw = (this.flags.source as string | undefined)?.trim().toLowerCase() ?? "auto";
    if (!SOURCE_FLAG_OPTIONS.includes(sourceRaw as SourceFlag)) {
      throw new ObjectifiedCliError({
        message: `Invalid --source ${JSON.stringify(this.flags.source)}.`,
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: `Choose one of: ${SOURCE_FLAG_OPTIONS.join(", ")}.`,
      });
    }
    const sourceFlag = sourceRaw as SourceFlag;

    const { raw: rawContent, parsed: parsedUnknown } = loadStructuredSpecFile(specPath);
    if (
      parsedUnknown === null ||
      typeof parsedUnknown !== "object" ||
      Array.isArray(parsedUnknown)
    ) {
      throw new ObjectifiedCliError({
        message: "Spec document must parse to a JSON object.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Root array or primitive is not a supported OpenAPI / Swagger / Arazzo document.",
      });
    }
    const document = parsedUnknown as Record<string, unknown>;
    const sourceKind = detectSourceKind(document, sourceFlag);

    let importFileDoc: Record<string, unknown> | undefined;
    const fromFileRaw =
      typeof this.flags["from-file"] === "string" ? this.flags["from-file"].trim() : "";
    if (fromFileRaw !== "") {
      importFileDoc = loadImportOptionsJson(fromFileRaw);
    }

    const optionsPayload =
      importFileDoc !== undefined ? buildOptionsFromImportFile(importFileDoc) : {};

    const fileName = pickStr(importFileDoc ?? {}, ["name"]);
    const fileSlug = pickStr(importFileDoc ?? {}, ["slug"]);
    const fileDesc = pickStr(importFileDoc ?? {}, ["description"]);
    const fileVersionId = pickStr(importFileDoc ?? {}, ["versionId", "version_id"]);
    const fileVersionDesc = pickStr(importFileDoc ?? {}, [
      "versionDescription",
      "version_description",
    ]);

    const nameFlag = typeof this.flags.name === "string" ? this.flags.name.trim() : "";
    const slugFlag = typeof this.flags.slug === "string" ? this.flags.slug.trim() : "";
    const descFlag =
      typeof this.flags.description === "string" ? this.flags.description : undefined;

    let versionIdMerged: string;
    let versionDescMerged: string | null;
    if (fileVersionId !== undefined && fileVersionId.trim() !== "") {
      versionIdMerged = fileVersionId.trim();
      versionDescMerged =
        fileVersionDesc !== undefined && fileVersionDesc.trim() !== ""
          ? fileVersionDesc.trim()
          : null;
    } else {
      const versionMeta = extractVersionMeta(document);
      versionIdMerged = versionMeta.versionId;
      versionDescMerged =
        fileVersionDesc !== undefined && fileVersionDesc.trim() !== ""
          ? fileVersionDesc.trim()
          : versionMeta.description;
    }

    let specDraft: SpecProjectDraft | undefined;
    if (createProjectFromSpec) {
      const derived = projectDraftFromSpecContent(rawContent, specPath);
      if (!derived.ok) {
        throw new ObjectifiedCliError({
          message: derived.reason,
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint: "Fix the spec or pass --project to target an existing project.",
        });
      }
      specDraft = derived.draft;
    }

    const tty = process.stdin.isTTY && process.stdout.isTTY;
    const yes = this.flags.yes === true;
    const quiet = this.flags.quiet === true;

    if (createProjectFromSpec && !tty && !yes) {
      throw new ObjectifiedCliError({
        message:
          "When stdin is not a TTY, omitting --project requires --yes to create a project non-interactively.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Example: `objectified spec import ./openapi.yaml --yes`",
      });
    }

    const visibilityFlag = this.flags.visibility as Visibility | undefined;

    const domainFlagRaw =
      typeof this.flags.domain === "string" ? this.flags.domain.trim() : undefined;

    let mergedName: string;
    let mergedSlug: string;
    let mergedDesc: string | null;

    if (createProjectFromSpec && specDraft !== undefined) {
      mergedName = nameFlag !== "" ? nameFlag : (fileName ?? specDraft.projectName);

      const resolveSlug = (): string => {
        if (slugFlag !== "") {
          const c = validateProjectSlug(slugFlag);
          if (!c.ok) {
            throw new ObjectifiedCliError({
              message: c.message,
              exitCode: EXIT_CODES.VALIDATION,
              title: "Validation failed",
              hint:
                c.suggestion !== undefined
                  ? `Try slug \`${c.suggestion}\`.`
                  : "Slug must match ^[a-z][a-z0-9-]{1,62}$.",
            });
          }
          return c.slug;
        }
        if (fileSlug !== undefined && fileSlug.trim() !== "") {
          const c = validateProjectSlug(fileSlug.trim());
          if (!c.ok) {
            throw new ObjectifiedCliError({
              message: c.message,
              exitCode: EXIT_CODES.VALIDATION,
              title: "Validation failed",
              hint:
                c.suggestion !== undefined
                  ? `Try slug \`${c.suggestion}\`.`
                  : "Slug must match ^[a-z][a-z0-9-]{1,62}$.",
            });
          }
          return c.slug;
        }
        return suggestProjectSlugFromSpec(mergedName, specPath);
      };
      mergedSlug = resolveSlug();

      if (descFlag !== undefined) {
        const t = descFlag.trim();
        mergedDesc = t === "" ? null : t;
      } else if (fileDesc !== undefined) {
        mergedDesc = fileDesc;
      } else {
        const d = specDraft.projectDescription.trim();
        mergedDesc = d === "" ? null : d;
      }
    } else {
      mergedName = "";
      mergedSlug = "";
      mergedDesc = null;
    }

    if (!this.context.json && !quiet) {
      this.output.text(`Detected: ${formatDetectedLine(sourceKind, document)}`);
      if (createProjectFromSpec && specDraft !== undefined) {
        const vis = visibilityFlag ?? "private";
        this.output.text("No --project provided; creating new project from spec:");
        this.output.text(`  name:        ${mergedName}`);
        this.output.text(`  slug:        ${mergedSlug}`);
        this.output.text(`  description: ${mergedDesc ?? ""}`);
        const domainShow = normalizeDomainCategory(domainFlagRaw);
        if (domainShow !== undefined) {
          this.output.text(`  domain:      ${domainShow}`);
        }
        this.output.text(`  visibility:  ${vis}`);
      }
    }

    const needConfirmNewProject =
      createProjectFromSpec && !this.context.json && tty && !yes && !quiet;

    if (needConfirmNewProject) {
      const { confirm } = await import("@inquirer/prompts");
      const ok = await confirm({
        message: "Create project and import spec?",
        default: true,
      });
      if (!ok) {
        throw new ObjectifiedCliError({
          message: "Import aborted.",
          exitCode: EXIT_CODES.MISUSE,
          title: "Aborted",
        });
      }
    }

    this.ensureAuthenticated();

    const profileKey = completionProfileCacheKey({
      baseUrl: this.context.baseUrl,
      profile: this.context.profile,
      tenantSlug: tenant,
    });

    let project: ProjectSchema;
    let freshProjectSlug: string | undefined;

    if (createProjectFromSpec) {
      const allowlistArr = await this.api.fetchProjectDomainsAllowlist(tenant);
      const allowlist = new Set(allowlistArr);
      const domainNorm = normalizeDomainCategory(domainFlagRaw);
      if (domainNorm !== undefined && !allowlist.has(domainNorm)) {
        throw new ObjectifiedCliError({
          message: `Unknown domain category '${domainNorm}'.`,
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint: `Choose one of: ${Array.from(allowlist).sort().join(", ")}`,
        });
      }

      const visibilityResolved: Visibility = visibilityFlag ?? "private";
      const baseMeta = specDraft !== undefined ? metadataRecordFromSpecDraft(specDraft) : {};

      const createBody = buildProjectCreateRequest({
        name: mergedName,
        slug: mergedSlug,
        description: mergedDesc,
        domainCategory: domainNorm ?? null,
        visibility: visibilityResolved,
        baseMetadata: Object.keys(baseMeta).length > 0 ? baseMeta : undefined,
      });

      let createdProject: ProjectSchema;
      try {
        createdProject = await this.api.createProject(tenant, createBody);
      } catch (e) {
        if (
          e instanceof ObjectifiedCliError &&
          e.exitCode === EXIT_CODES.CONFLICT &&
          /\bslug\b/i.test(e.message) &&
          /\balready exists\b|\balready in use\b/i.test(e.message)
        ) {
          throw new ObjectifiedCliError({
            message: `Project slug '${mergedSlug}' is already in use for this tenant.`,
            exitCode: EXIT_CODES.CONFLICT,
            title: e.title ?? "Conflict",
            hint: "Pass a different --slug or delete the existing project first.",
            requestId: e.requestId,
            retriesAttempted: e.retriesAttempted,
          });
        }
        throw e;
      }
      project = createdProject;
      freshProjectSlug = mergedSlug;

      if (!this.context.json && !quiet) {
        const langAscii = localePrefersAsciiTable(process.env);
        const mark = langAscii ? "[ok]" : "✔";
        const id = createdProject.id;
        const idShort = id.length <= 14 ? id : `${id.slice(0, 8)}…`;
        this.output.text(`${mark} Created project ${mergedSlug} (${idShort})`);
      }
    } else {
      project = await resolveProjectForTenant(this.api, tenant, rawProject, profileKey);
    }

    const projectName = createProjectFromSpec
      ? mergedName
      : nameFlag !== ""
        ? nameFlag
        : (fileName ?? project.name);
    const projectSlug = createProjectFromSpec
      ? mergedSlug
      : slugFlag !== ""
        ? slugFlag
        : (fileSlug ?? project.slug);

    let projectDescription: string | null;
    if (createProjectFromSpec) {
      projectDescription = mergedDesc;
    } else if (descFlag !== undefined) {
      const t = descFlag.trim();
      projectDescription = t === "" ? null : t;
    } else if (fileDesc !== undefined) {
      projectDescription = fileDesc;
    } else {
      projectDescription = project.description ?? null;
    }

    const body = {
      sourceKind,
      document,
      project: {
        name: projectName,
        slug: projectSlug,
        description: projectDescription,
      },
      version: {
        versionId: versionIdMerged,
        description: versionDescMerged,
      },
      options: optionsPayload,
      existingProjectId: project.id,
    };

    if (!this.context.json && !quiet) {
      this.output.text(
        `Target:   tenant=${tenant}, project=${projectSlug} (${project.id.slice(0, 4)}…)`,
      );
    }

    try {
      const created = await this.api.createImportJob(tenant, body);

      const job = isPollingTerminalState(created.state)
        ? created
        : await followImportJob({
            api: this.api,
            tenantSlug: tenant,
            initial: created,
            spinnerText: progressSpinnerText,
            createSpinner: (t) => this.output.spinner(t),
          });

      if (this.context.json) {
        this.output.json(job);
      }

      this.finishImportJob(job, projectSlug);
    } catch (err) {
      if (
        freshProjectSlug !== undefined &&
        err instanceof ObjectifiedCliError &&
        err.exitCode !== EXIT_CODES.MISUSE
      ) {
        throw this.augmentFreshProjectFailure(err, freshProjectSlug);
      }
      throw err;
    }
  }

  private augmentFreshProjectFailure(
    err: ObjectifiedCliError,
    projectSlug: string,
  ): ObjectifiedCliError {
    const tail = `An empty project '${projectSlug}' may remain; delete with \`objectified projects delete ${projectSlug} --force\` before retrying if needed.`;
    return new ObjectifiedCliError({
      message: err.message,
      exitCode: err.exitCode,
      title: err.title,
      hint: err.hint !== undefined && err.hint !== "" ? `${err.hint} ${tail}` : tail,
      requestId: err.requestId,
      retriesAttempted: err.retriesAttempted,
    });
  }

  private finishImportJob(job: ImportJobResponse, projectSlug: string): void {
    if (job.state === "pending-approval") {
      if (!this.context.json) {
        this.output.text(
          `Import job ${job.jobId} is pending approval (review in the app or via a future CLI flag).`,
        );
      }
      return;
    }

    if (job.state === "canceled") {
      throw new ObjectifiedCliError({
        message: "Import job was canceled.",
        exitCode: EXIT_CODES.GENERIC,
        title: "Canceled",
        hint: "Re-queue an import or inspect tenant logs if this was unexpected.",
        requestId: this.api.lastRequestId,
        retriesAttempted: this.api.lastRetriesAttempted,
      });
    }

    if (job.state === "failed" || job.state === "rolled-back") {
      const msg =
        job.error !== undefined && job.error !== null && typeof job.error.message === "string"
          ? job.error.message
          : `Import ${job.state}.`;
      throw new ObjectifiedCliError({
        message: msg,
        exitCode: EXIT_CODES.SERVER_ERROR,
        title: "Import failed",
        hint:
          this.api.lastRequestId !== undefined && this.api.lastRequestId !== ""
            ? `Request ID: ${this.api.lastRequestId}`
            : "Retry later or inspect API logs.",
        requestId: this.api.lastRequestId,
        retriesAttempted: this.api.lastRetriesAttempted,
      });
    }

    if (job.state !== "completed") {
      throw new ObjectifiedCliError({
        message: `Import ended in unexpected state ${JSON.stringify(job.state)}.`,
        exitCode: EXIT_CODES.GENERIC,
        title: "Import failed",
        requestId: this.api.lastRequestId,
        retriesAttempted: this.api.lastRetriesAttempted,
      });
    }

    if (this.context.json) {
      return;
    }

    const vid =
      job.result?.versionId ??
      pickStr(
        job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
          ? (job.summary as Record<string, unknown>)
          : {},
        ["versionId", "version_id"],
      ) ??
      "?";
    const langAscii = localePrefersAsciiTable(process.env);
    const mark = langAscii ? "[ok]" : "✔";
    this.output.text(
      `${mark} Imported as draft revision ${vid} (job ${job.jobId.slice(0, 8)}…) into project ${projectSlug}.`,
    );

    const cls = formatClassesSummary(
      job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
        ? (job.summary as Record<string, unknown>)
        : undefined,
    );
    if (cls !== undefined) {
      this.output.text(`  ${cls}`);
    }

    const hint = formatSummaryFollowUp(job, projectSlug);
    if (hint !== undefined) {
      this.output.text(`  ${hint}`);
    }
  }
}
