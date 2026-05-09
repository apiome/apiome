import { BaseCommand } from "../../base-command.js";
import { docsTopicSpecImport } from "../../lib/docs-content.js";

export default class DocsSpecImport extends BaseCommand {
  static description =
    "Flags for CI pipelines: dry-run, review/hold, NDJSON streaming, reports, and exit codes.";

  static examples = [
    "<%= config.bin %> <%= command.id %>",
    "<%= config.bin %> --json <%= command.id %>",
    "<%= config.bin %> spec import ./openapi.yaml --help",
  ];

  static seeAlso = [
    "spec import",
    "spec import status",
    "spec import commit",
    "spec import cancel",
    "docs errors",
    "docs output",
  ];

  run(): Promise<void> {
    if (this.context.json) {
      this.output.json({ topic: "spec-import", body: docsTopicSpecImport });
      return Promise.resolve();
    }
    this.output.text(docsTopicSpecImport);
    return Promise.resolve();
  }
}
