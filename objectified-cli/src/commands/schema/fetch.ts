import { Args, Flags } from "@oclif/core";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { open, writeFile } from "node:fs/promises";

import { BaseCommand } from "../../base-command.js";
import { formatApiError } from "../../lib/client.js";
import { httpStatusToCliError, ObjectifiedCliError } from "../../lib/errors.js";
import { EXIT_CODES } from "../../lib/exit-codes.js";
import {
  buildSchemaFetchAcceptHeader,
  normalizeExpectSha256Hex,
  parseTenantProjectVersionRef,
} from "../../lib/schema/schema-fetch-helpers.js";
import { stringify as stringifyYaml } from "yaml";

async function readFailedResponseBody(res: Response): Promise<string> {
  const text = await res.text();
  try {
    return formatApiError(JSON.parse(text) as unknown);
  } catch {
    return text.trim() !== "" ? text.slice(0, 800) : `HTTP ${String(res.status)}`;
  }
}

export default class SchemaFetch extends BaseCommand {
  static description =
    "Download the published OpenAPI bundle or one class schema from GET /v1/schema/{tenant}/{project}/{version}[/{class}] (stdin/stdout friendly; optional checksum gate).";

  static examples = [
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --format yaml > spec.yaml",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --class Charge --format json",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --output ./build/openapi.json",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --expect-sha256 <64-hex>",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --latest",
    "<%= config.bin %> <%= command.id %> acme-corp/payments-api/2.1.0 --accept tag:stable",
  ];

  static seeAlso = ["browse versions", "versions show", "docs errors"];

  static args = {
    ref: Args.string({
      description:
        "Published target as tenant/project/version (slashes separate the three slugs; semver, latest, or server-resolved tag via --accept).",
      required: true,
    }),
  };

  static flags = {
    class: Flags.string({
      description: "Fetch only this class (GET adds /{class_name}; uses content negotiation for JSON vs YAML).",
      char: "c",
    }),
    format: Flags.string({
      description: "Output serialization. Full-bundle YAML is converted client-side from JSON.",
      options: ["json", "yaml"],
      default: "json",
    }),
    output: Flags.string({
      description: "Write bytes to this path instead of stdout.",
      char: "o",
    }),
    "expect-sha256": Flags.string({
      description:
        "SHA-256 of the emitted bytes (after --format); exit 7 when the digest does not match (CI drift gate).",
    }),
    latest: Flags.boolean({
      description: "Send version_slug `latest` (overrides the third segment of the positional ref).",
      default: false,
    }),
    accept: Flags.string({
      description:
        "Extra Accept token forwarded to the API (for example tag:stable); combined with class format negotiation when --class is set.",
    }),
  };

  async run(): Promise<void> {
    const refRaw = this.commandArgs.ref;
    const refStr = typeof refRaw === "string" ? refRaw : "";
    const { tenantSlug, projectSlug, versionSlug: versionFromRef } =
      parseTenantProjectVersionRef(refStr);
    const versionSlug = this.flags.latest === true ? "latest" : versionFromRef;

    const classRaw = this.flags.class;
    const className = typeof classRaw === "string" ? classRaw.trim() : "";

    const formatRaw = this.flags.format;
    const format: "json" | "yaml" = formatRaw === "yaml" ? "yaml" : "json";

    const acceptRaw = this.flags.accept;
    const acceptTag = typeof acceptRaw === "string" ? acceptRaw.trim() : "";

    const acceptHeader = buildSchemaFetchAcceptHeader({
      format,
      className: className !== "" ? className : undefined,
      acceptTag: acceptTag !== "" ? acceptTag : undefined,
    });

    const res = await this.api.fetchOpenApiPublishedSchema({
      tenantSlug,
      projectSlug,
      versionSlug,
      className: className !== "" ? className : undefined,
      acceptHeader,
    });

    if (!res.ok) {
      const msg = await readFailedResponseBody(res);
      const rid = res.headers.get("x-request-id") ?? res.headers.get("X-Request-Id") ?? undefined;
      throw httpStatusToCliError(res.status, msg, {
        requestId: rid ?? this.api.lastRequestId,
        retriesAttempted: this.api.lastRetriesAttempted,
        credentialsWereSent: Boolean(this.apiAuth.apiKey || this.apiAuth.bearer),
      });
    }

    const outRaw = this.flags.output;
    const outPath = typeof outRaw === "string" ? outRaw.trim() : "";
    const expectRaw = this.flags["expect-sha256"];
    const expectedSha =
      typeof expectRaw === "string" && expectRaw.trim() !== ""
        ? normalizeExpectSha256Hex(expectRaw)
        : undefined;

    const convertFullBundleToYaml = format === "yaml" && className === "";
    if (convertFullBundleToYaml) {
      let body = Buffer.from(await res.arrayBuffer());
      let parsed: unknown;
      try {
        parsed = JSON.parse(body.toString("utf8")) as unknown;
      } catch {
        throw new ObjectifiedCliError({
          message: "Schema response was not valid JSON; cannot emit YAML for the full bundle.",
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint: "The version-level endpoint returned non-JSON; report this with x-request-id from verbose logs.",
        });
      }
      body = Buffer.from(stringifyYaml(parsed), "utf8");

      if (expectedSha !== undefined) {
        const got = createHash("sha256").update(body).digest("hex");
        if (got !== expectedSha) {
          throw new ObjectifiedCliError({
            message: `SHA-256 mismatch: expected ${expectedSha}, got ${got}.`,
            exitCode: EXIT_CODES.VALIDATION,
            title: "Checksum mismatch",
            hint: "The downloaded schema bytes differ from --expect-sha256 (useful to detect unexpected drift in CI).",
          });
        }
      }
      if (outPath !== "") {
        await writeFile(outPath, body);
      } else {
        process.stdout.write(body);
      }
      return;
    }

    const hasher = createHash("sha256");
    const writer = outPath !== "" ? await open(outPath, "w") : undefined;

    const writeStdout = async (chunk: Buffer): Promise<void> => {
      if (!process.stdout.write(chunk)) {
        await once(process.stdout, "drain");
      }
    };

    try {
      if (res.body === null) {
        const chunk = Buffer.from(await res.arrayBuffer());
        hasher.update(chunk);
        if (writer !== undefined) {
          await writer.write(chunk);
        } else {
          await writeStdout(chunk);
        }
      } else {
        const reader = res.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = Buffer.from(value);
          hasher.update(chunk);
          if (writer !== undefined) {
            await writer.write(chunk);
          } else {
            await writeStdout(chunk);
          }
        }
      }
    } finally {
      await writer?.close();
    }

    if (expectedSha !== undefined) {
      const got = hasher.digest("hex");
      if (got !== expectedSha) {
        throw new ObjectifiedCliError({
          message: `SHA-256 mismatch: expected ${expectedSha}, got ${got}.`,
          exitCode: EXIT_CODES.VALIDATION,
          title: "Checksum mismatch",
          hint: "The downloaded schema bytes differ from --expect-sha256 (useful to detect unexpected drift in CI).",
        });
      }
    }
  }
}
