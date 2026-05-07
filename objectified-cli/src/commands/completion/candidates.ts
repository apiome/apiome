import { Flags } from "@oclif/core";

import { BaseCommand } from "../../base-command.js";
import { computeCompletionCandidates } from "../../lib/completion/candidates-logic.js";

function readStdinUtf8(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    process.stdin.on("data", (d: string | Buffer) => {
      chunks.push(typeof d === "string" ? Buffer.from(d) : d);
    });
    process.stdin.on("end", () => {
      resolve(Buffer.concat(chunks).toString("utf8"));
    });
    process.stdin.on("error", reject);
  });
}

export default class CompletionCandidates extends BaseCommand {
  static hidden = true;

  static description = "Emit newline-separated completion candidates (stdin: one CLI token per line).";

  static examples = [
    "printf '%s\\n' objectified projects | <%= config.bin %> --no-json <%= command.id %> --shell bash --cword 1",
    "printf '%s\\n' objectified projects list | <%= config.bin %> --no-json <%= command.id %> --shell bash --cword 2",
  ];

  static flags = {
    shell: Flags.string({
      description: "Shell driver",
      options: ["bash", "zsh", "fish", "powershell"],
      required: true,
    }),
    cword: Flags.integer({
      description: "Index into token list for the word being completed",
      required: true,
    }),
  };

  async run(): Promise<void> {
    const { flags } = await this.parse(CompletionCandidates);
    const cword = flags.cword;

    const raw = await readStdinUtf8();
    const words = raw.split("\n").filter((line) => line !== "");

    if (words.length === 0 || cword < 0) {
      return;
    }

    const candidates = await computeCompletionCandidates({
      config: this.config,
      api: this.api,
      baseUrl: this.context.baseUrl,
      configDoc: this.configDoc,
      env: process.env,
      words,
      cword,
    });

    for (const line of candidates) {
      process.stdout.write(`${line}\n`);
    }
  }
}
