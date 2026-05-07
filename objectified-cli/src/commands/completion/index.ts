import { BaseCommand } from "../../base-command.js";

export default class CompletionIndex extends BaseCommand {
  static description =
    "Install or print shell completion scripts for bash, zsh, fish, or PowerShell.";

  static examples = [
    "<%= config.bin %> <%= command.id %> install",
    "<%= config.bin %> <%= command.id %> install zsh",
    "<%= config.bin %> <%= command.id %> show bash",
    "<%= config.bin %> <%= command.id %> uninstall",
  ];

  static seeAlso = ["docs completions", "hello", "config path"];

  run(): Promise<void> {
    const topics = [
      { command: "completion install [bash|zsh|fish|powershell]", summary: "Append completion glue to your shell rc file" },
      { command: "completion show [bash|zsh|fish|powershell]", summary: "Print completion glue to stdout" },
      { command: "completion uninstall", summary: "Remove Objectified completion blocks we added" },
    ];

    if (this.context.json) {
      this.output.json({ topic: "completion", commands: topics });
      return Promise.resolve();
    }

    this.output.table(
      topics.map((t) => ({ command: t.command, summary: t.summary })),
      [
        { key: "command", label: "Command" },
        { key: "summary", label: "Summary" },
      ],
    );
    this.output.text(`\nTry ${this.config.bin} docs completions for behavior and caching notes.`);
    return Promise.resolve();
  }
}
