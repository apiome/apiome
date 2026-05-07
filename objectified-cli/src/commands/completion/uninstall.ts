import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { BaseCommand } from "../../base-command.js";
import { chalkForContext } from "../../lib/output.js";
import { readRcSafe, stripMarkedCompletionBlock } from "../../lib/completion/rc-file.js";

function powershellProfilePath(): string {
  const home = os.homedir();
  if (process.platform === "win32") {
    return path.join(home, "Documents", "PowerShell", "Microsoft.PowerShell_profile.ps1");
  }
  return path.join(home, ".config", "powershell", "Microsoft.PowerShell_profile.ps1");
}

export default class CompletionUninstall extends BaseCommand {
  static description = "Remove Objectified completion blocks added by `completion install`.";

  static examples = [
    "<%= config.bin %> <%= command.id %>",
    "<%= config.bin %> --json <%= command.id %>",
  ];

  static seeAlso = ["completion install", "docs completions"];

  run(): Promise<void> {
    const bin = this.config.bin;
    const home = os.homedir();
    const targets = [
      path.join(home, ".bashrc"),
      path.join(home, ".zshrc"),
      powershellProfilePath(),
      path.join(home, ".config", "fish", "completions", `${bin}.fish`),
    ];

    const touched: string[] = [];

    for (const file of targets) {
      const before = readRcSafe(file);
      if (before === "") continue;
      const after = stripMarkedCompletionBlock(before);
      if (after === before) continue;

      if (after.trim() === "" && file.endsWith(".fish")) {
        fs.unlinkSync(file);
        touched.push(file);
        continue;
      }

      fs.writeFileSync(file, after.endsWith("\n") ? after : after + "\n", "utf8");
      touched.push(file);
    }

    if (this.context.json) {
      this.output.json({ removedFrom: touched });
      return Promise.resolve();
    }

    if (touched.length === 0) {
      this.output.text(
        chalkForContext(this.context.color).bold("No Objectified completion markers found."),
      );
      return Promise.resolve();
    }

    this.output.text(
      `${chalkForContext(this.context.color).bold("Removed")} completion blocks from:\n${touched.map((t) => `  - ${t}`).join("\n")}`,
    );
    return Promise.resolve();
  }
}
