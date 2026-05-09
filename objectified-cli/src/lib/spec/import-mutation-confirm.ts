import { ObjectifiedCliError } from "../errors.js";
import { EXIT_CODES } from "../exit-codes.js";

export async function ensureImportMutationConfirmed(opts: {
  yes: boolean;
  verbLabel: string;
}): Promise<void> {
  const tty = process.stdin.isTTY && process.stdout.isTTY;
  if (!tty && !opts.yes) {
    throw new ObjectifiedCliError({
      message: `This command requires --yes when stdin is not a TTY (${opts.verbLabel}).`,
      exitCode: EXIT_CODES.CONFLICT,
      title: "Conflict",
      hint: `Example: \`objectified spec import ${opts.verbLabel} <job-id> --yes\``,
    });
  }
  if (tty && !opts.yes) {
    const { confirm } = await import("@inquirer/prompts");
    const ok = await confirm({
      message: `${opts.verbLabel === "commit" ? "Commit" : "Cancel"} this import job?`,
      default: false,
    });
    if (!ok) {
      throw new ObjectifiedCliError({
        message: `${opts.verbLabel} aborted.`,
        exitCode: EXIT_CODES.MISUSE,
        title: "Aborted",
      });
    }
  }
}
