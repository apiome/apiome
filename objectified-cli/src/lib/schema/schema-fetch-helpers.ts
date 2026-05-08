import { ObjectifiedCliError } from "../errors.js";
import { EXIT_CODES } from "../exit-codes.js";

export function parseTenantProjectVersionRef(raw: string): {
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
} {
  const s = raw.trim();
  const first = s.indexOf("/");
  const second = s.indexOf("/", first + 1);
  const third = s.indexOf("/", second + 1);
  if (first <= 0 || second <= first + 1 || second >= s.length - 1 || third !== -1) {
    throw new ObjectifiedCliError({
      message: "Expected tenant/project/version (for example acme-corp/payments-api/2.1.0).",
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid argument",
      hint: "Pass one slash-separated triple: tenant_slug, project_slug, and version_slug.",
    });
  }
  const tenantSlug = s.slice(0, first).trim();
  const projectSlug = s.slice(first + 1, second).trim();
  const versionSlug = s.slice(second + 1).trim();
  if (tenantSlug === "" || projectSlug === "" || versionSlug === "") {
    throw new ObjectifiedCliError({
      message: "Tenant slug, project slug, and version slug must be non-empty.",
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid argument",
      hint: "Use `objectified schema fetch tenant/project/version`.",
    });
  }
  return { tenantSlug, projectSlug, versionSlug };
}

/** Normalize CLI `--expect-sha256` to lowercase 64 hex chars (allows optional 0x). */
export function normalizeExpectSha256Hex(raw: string): string {
  const s = raw.trim().toLowerCase().replace(/\s+/g, "");
  const hex = s.startsWith("0x") ? s.slice(2) : s;
  if (!/^[0-9a-f]{64}$/.test(hex)) {
    throw new ObjectifiedCliError({
      message: "--expect-sha256 must be a 64-character hexadecimal SHA-256 digest.",
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid argument",
      hint: "Pass the full hex digest of the bytes this command writes (after --format conversion).",
    });
  }
  return hex;
}

/** Builds Accept for tag negotiation plus JSON/YAML when fetching a single class. */
export function buildSchemaFetchAcceptHeader(opts: {
  format: "json" | "yaml";
  className?: string;
  acceptTag?: string;
}): string | undefined {
  const parts: string[] = [];
  const tag = opts.acceptTag?.trim();
  if (tag !== undefined && tag !== "") {
    parts.push(tag);
  }
  if (opts.className !== undefined && opts.className !== "") {
    parts.push(opts.format === "yaml" ? "application/yaml" : "application/json");
  }
  if (parts.length === 0) {
    return undefined;
  }
  return parts.join(", ");
}
