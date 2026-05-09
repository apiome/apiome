import { ObjectifiedCliError } from "../errors.js";
import { EXIT_CODES } from "../exit-codes.js";
import { readLastImportJobId } from "./last-import-job-cache.js";

export function resolveImportJobRef(opts: {
  tenantSlug: string;
  positionalJobId: string | undefined;
  last: boolean;
}): string {
  const last = opts.last;
  const pos = typeof opts.positionalJobId === "string" ? opts.positionalJobId.trim() : "";

  if (last) {
    if (pos !== "") {
      throw new ObjectifiedCliError({
        message: "Pass either a job id argument or --last, not both.",
        exitCode: EXIT_CODES.MISUSE,
        title: "Invalid usage",
        hint: "Omit the job id when using --last, or drop --last and pass the job UUID.",
      });
    }
    const cached = readLastImportJobId(opts.tenantSlug);
    if (cached === undefined || cached === "") {
      throw new ObjectifiedCliError({
        message: `No cached last import job for tenant ${JSON.stringify(opts.tenantSlug)}.`,
        exitCode: EXIT_CODES.NOT_FOUND,
        title: "Not found",
        hint: "Run `objectified spec import <file> …` first, or pass an explicit job id.",
      });
    }
    return cached;
  }

  if (pos === "") {
    throw new ObjectifiedCliError({
      message: "Job id is required unless you pass --last.",
      exitCode: EXIT_CODES.MISUSE,
      title: "Invalid usage",
      hint: "Example: `objectified spec import status <job-id>` or `objectified spec import status --last`.",
    });
  }
  return pos;
}
