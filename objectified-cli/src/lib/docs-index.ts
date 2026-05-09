/** Topics served under \`objectified docs <topic>\` (parent command lists this table). */

export type DocsTopicMeta = { topic: string; summary: string };

export const DOCS_TOPIC_INDEX: DocsTopicMeta[] = [
  { topic: "errors", summary: "Exit codes, stderr shape, and debugging hints" },
  {
    topic: "spec-import",
    summary:
      "objectified spec import — CI flags (--dry-run, --review, --report, --ndjson); async status/commit/cancel",
  },
  { topic: "output", summary: "TTY vs JSON, quiet, verbose, and color rules" },
  { topic: "profiles", summary: "config.toml profiles, defaults, and resolution order" },
  {
    topic: "completions",
    summary: "Shell completions (install/show/uninstall, cached dynamic lists)",
  },
  { topic: "plugins", summary: "Plugin roadmap for third-party commands" },
  { topic: "telemetry", summary: "Telemetry posture and verbose diagnostics" },
];
