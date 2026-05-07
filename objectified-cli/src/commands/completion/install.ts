import { Args } from "@oclif/core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { BaseCommand } from "../../base-command.js";
import { chalkForContext } from "../../lib/output.js";
import {
  bashCompletionBody,
  fishCompletionBody,
  powershellCompletionBody,
  zshCompletionBody,
} from "../../lib/completion/shell-snippets.js";
import { readRcSafe, upsertMarkedCompletionBlock } from "../../lib/completion/rc-file.js";

type CompletionShell = "bash" | "zsh" | "fish" | "powershell";

function inferShell(): CompletionShell {
  if (process.platform === "win32") return "powershell";
  const sh = process.env.SHELL ?? "";
  if (sh.includes("zsh")) return "zsh";
  if (sh.includes("fish")) return "fish";
  return "bash";
}

function powershellProfilePath(): string {
  const home = os.homedir();
  if (process.platform === "win32") {
    return path.join(home, "Documents", "PowerShell", "Microsoft.PowerShell_profile.ps1");
  }
  return path.join(home, ".config", "powershell", "Microsoft.PowerShell_profile.ps1");
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

export default class CompletionInstall extends BaseCommand {
  static description = "Append shell completion glue to the right startup file for your shell.";

  static args = {
    shell: Args.string({
      description: "Shell to install for (default: inferred from $SHELL / OS)",
      options: ["bash", "zsh", "fish", "powershell"],
      required: false,
    }),
  };

  static examples = [
    "<%= config.bin %> <%= command.id %>",
    "<%= config.bin %> <%= command.id %> fish",
    "<%= config.bin %> --profile staging <%= command.id %> zsh",
  ];

  static seeAlso = ["completion show", "docs completions", "config path"];

  async run(): Promise<void> {
    const { args } = await this.parse(CompletionInstall);
    const shell = (args.shell ?? inferShell()) as CompletionShell;
    const bin = this.config.bin;
    const inner = completionInner(shell, bin);

    if (shell === "bash") {
      const rc = path.join(os.homedir(), ".bashrc");
      const next = upsertMarkedCompletionBlock(readRcSafe(rc), inner);
      fs.writeFileSync(rc, next.endsWith("\n") ? next : next + "\n", "utf8");
      if (this.context.json) {
        this.output.json({ shell, rcFile: rc, action: "installed" });
        return;
      }
      this.output.text(
        `${chalkForContext(this.context.color).bold("Installed")} bash completion into ${rc}`,
      );
      this.output.text(`Run ${chalkForContext(this.context.color).cyan(`source ${rc}`)} to load it in this session.`);
      return;
    }

    if (shell === "zsh") {
      const rc = path.join(os.homedir(), ".zshrc");
      const next = upsertMarkedCompletionBlock(readRcSafe(rc), inner);
      fs.writeFileSync(rc, next.endsWith("\n") ? next : next + "\n", "utf8");
      if (this.context.json) {
        this.output.json({ shell, rcFile: rc, action: "installed" });
        return;
      }
      this.output.text(
        `${chalkForContext(this.context.color).bold("Installed")} zsh completion into ${rc}`,
      );
      this.output.text(`Run ${chalkForContext(this.context.color).cyan(`source ${rc}`)} to load it in this session.`);
      return;
    }

    if (shell === "fish") {
      const dir = path.join(os.homedir(), ".config", "fish", "completions");
      fs.mkdirSync(dir, { recursive: true });
      const rc = path.join(dir, `${bin}.fish`);
      const next = upsertMarkedCompletionBlock(readRcSafe(rc), inner);
      fs.writeFileSync(rc, next.endsWith("\n") ? next : next + "\n", "utf8");
      if (this.context.json) {
        this.output.json({ shell, rcFile: rc, action: "installed" });
        return;
      }
      this.output.text(
        `${chalkForContext(this.context.color).bold("Installed")} fish completion into ${rc}`,
      );
      this.output.text(`Open a new fish session or run ${chalkForContext(this.context.color).cyan("exec fish")}.`);
      return;
    }

    const rc = powershellProfilePath();
    fs.mkdirSync(path.dirname(rc), { recursive: true });
    const next = upsertMarkedCompletionBlock(readRcSafe(rc), inner);
    fs.writeFileSync(rc, next.endsWith("\n") ? next : next + "\n", "utf8");
    if (this.context.json) {
      this.output.json({ shell, rcFile: rc, action: "installed" });
      return;
    }
    this.output.text(
      `${chalkForContext(this.context.color).bold("Installed")} PowerShell completion into ${rc}`,
    );
    this.output.text(`Run ${chalkForContext(this.context.color).cyan(`. "${rc}"`)} to load it in this session.`);
  }
}
