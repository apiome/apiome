import { Args } from "@oclif/core";

import { BaseCommand } from "../../base-command.js";
import {
  bashCompletionBody,
  fishCompletionBody,
  powershellCompletionBody,
  zshCompletionBody,
} from "../../lib/completion/shell-snippets.js";
import { upsertMarkedCompletionBlock } from "../../lib/completion/rc-file.js";

type CompletionShell = "bash" | "zsh" | "fish" | "powershell";

function inferShell(): CompletionShell {
  if (process.platform === "win32") return "powershell";
  const sh = process.env.SHELL ?? "";
  if (sh.includes("zsh")) return "zsh";
  if (sh.includes("fish")) return "fish";
  return "bash";
}

function completionInner(shell: CompletionShell, bin: string): string {
  switch (shell) {
    case "bash":
      return bashCompletionBody(bin);
    case "zsh":
      return zshCompletionBody(bin);
    case "fish":
      return fishCompletionBody(bin);
    case "powershell":
      return powershellCompletionBody(bin);
    default:
      throw new Error(`unsupported shell: ${String(shell)}`);
  }
}

export default class CompletionShow extends BaseCommand {
  static description = "Print shell completion glue (with marker comments) to stdout.";

  static args = {
    shell: Args.string({
      description: "Shell to generate",
      options: ["bash", "zsh", "fish", "powershell"],
      required: false,
    }),
  };

  static examples = [
    "<%= config.bin %> <%= command.id %>",
    "<%= config.bin %> <%= command.id %> bash",
    "<%= config.bin %> <%= command.id %> fish >> ~/.config/fish/completions/objectified.fish",
  ];

  static seeAlso = ["completion install", "docs completions"];

  async run(): Promise<void> {
    const { args } = await this.parse(CompletionShow);
    const shell = (args.shell ?? inferShell()) as CompletionShell;
    const inner = completionInner(shell, this.config.bin);
    const marked = upsertMarkedCompletionBlock("", inner);

    if (this.context.json) {
      this.output.json({
        shell,
        script: marked.trimEnd(),
        hint:
          shell === "fish"
            ? `Default install path: ~/.config/fish/completions/${this.config.bin}.fish`
            : shell === "powershell"
              ? "Append to $PROFILE on Windows or ~/.config/powershell/Microsoft.PowerShell_profile.ps1"
              : shell === "zsh"
                ? "~/.zshrc"
                : "~/.bashrc",
      });
      return;
    }

    process.stdout.write(marked.endsWith("\n") ? marked : `${marked}\n`);
  }
}
