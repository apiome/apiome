/** User-facing CLI error: message is printed to stderr without a stack trace; process exits non-zero. */
export class CliError extends Error {
  readonly exitCode: number;
  readonly hint?: string;

  constructor(message: string, opts: { exitCode?: number; hint?: string } = {}) {
    super(message);
    this.name = "CliError";
    this.exitCode = opts.exitCode ?? 1;
    this.hint = opts.hint;
  }
}
