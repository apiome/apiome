import { Command, CommandHelp, Help, type HelpSectionRenderer } from "@oclif/core";
import supportsColor from "supports-color";

type HelpGenCtx = Parameters<HelpSectionRenderer>[0];
type HelpGenHeader = Parameters<HelpSectionRenderer>[1];

/** Same value as `src/lib/constants.ts` — inlined so oclif’s dynamic help import does not pull extra modules. */
const DEFAULT_BASE_URL = "https://api.objectified.dev";

const GLOBAL_FLAGS_BODY = [
  "Global flags apply to every command:",
  "",
  `  --api-key       OBJECTIFIED_API_KEY       Direct API-key auth (overrides config api_key; never persisted unless auth login --api-key)`,
  `  --api-key-file                            Read API key from a file (single line)`,
  `  --base-url      OBJECTIFIED_BASE_URL      Root REST endpoint (built-in default: ${DEFAULT_BASE_URL})`,
  `  --config        OBJECTIFIED_CONFIG        config.toml (default: XDG config dir, or %APPDATA%\\Objectified on Windows)`,
  `  --json          OBJECTIFIED_JSON=1        Machine-readable JSON (auto when stdout is not a TTY)`,
  `  --no-color      NO_COLOR=1                Disable ANSI color (auto when stdout is not a TTY)`,
  `  --profile       OBJECTIFIED_PROFILE       Profile name; falls back to default_profile in config, else "default"`,
  `  --quiet, -q                               Suppress non-error stdout`,
  `  --verbose       OBJECTIFIED_VERBOSE=1     Verbose stderr logging`,
  "",
  "Resolution order for base URL (highest precedence wins):",
  "  1. Command-line flag            (--base-url=…)",
  "  2. Environment variable         (OBJECTIFIED_BASE_URL=…)",
  "  3. Config [profile.NAME]        (base_url=…)",
  "  4. Config [default]              (base_url=…)",
  `  5. Built-in default              (${DEFAULT_BASE_URL})`,
  "",
  "Resolution order for API key: --api-key, OBJECTIFIED_API_KEY, --api-key-file, then api_key in config ([profile] over [default]), then credentials from auth login --api-key (#3195).",
  "Resolution order for tenant slug: OBJECTIFIED_TENANT, then config profile / [default] (tenant_slug).",
].join("\n");

const FLAG_GROUP_ORDER = ["Required", "Common", "Output", "Auth", "Other"] as const;

function compactSections<T>(xs: (T | undefined)[]): T[] {
  return xs.filter((x): x is T => Boolean(x));
}

function parseBooleanArg(value: string): boolean | undefined {
  const normalized = value.trim().toLowerCase();
  if (normalized === "1" || normalized === "true" || normalized === "yes") return true;
  if (normalized === "0" || normalized === "false" || normalized === "no") return false;
  return undefined;
}

function argvColorFlag(argv: string[]): boolean | undefined {
  let out: boolean | undefined;
  for (const arg of argv) {
    if (arg === "--color") {
      out = true;
      continue;
    }
    if (arg.startsWith("--color=")) {
      const parsed = parseBooleanArg(arg.slice("--color=".length));
      if (parsed !== undefined) out = parsed;
      continue;
    }
    if (arg === "--no-color") {
      out = false;
      continue;
    }
    if (arg.startsWith("--no-color=")) {
      const parsed = parseBooleanArg(arg.slice("--no-color=".length));
      if (parsed !== undefined) out = !parsed;
    }
  }
  return out;
}

function helpShouldStripAnsi(optsStrip: boolean | undefined, argv: string[]): boolean {
  if (optsStrip === true) return true;
  if (optsStrip === false) return false;
  const colorFlag = argvColorFlag(argv);
  if (colorFlag === false) return true;
  if (colorFlag === true) return false;
  if (process.env.NO_COLOR !== undefined && process.env.NO_COLOR !== "") return true;
  return typeof supportsColor.stdout !== "object" || !process.stdout.isTTY;
}

type CommandWithSeeAlso = Command.Loadable & { seeAlso?: string[] };

class ObjectifiedCommandHelp extends CommandHelp {
  private flagHelpSections(
    flags: Command.Flag.Any[],
  ): { header: string; body: [string, string | undefined][] }[] {
    const buckets = new Map<string, Command.Flag.Any[]>();

    for (const flag of flags) {
      const raw = flag.helpGroup?.trim();
      const bucket = raw && raw.length > 0 ? raw : "Other";
      const arr = buckets.get(bucket);
      if (arr) arr.push(flag);
      else buckets.set(bucket, [flag]);
    }

    const sortFlags = (fs: Command.Flag.Any[]) =>
      [...fs].sort((a, b) => {
        return a.name.localeCompare(b.name);
      });

    const out: { header: string; body: [string, string | undefined][] }[] = [];

    for (const name of FLAG_GROUP_ORDER) {
      const fs = buckets.get(name);
      if (!fs?.length) continue;
      const body = this.flags(sortFlags(fs));
      if (body) out.push({ header: name.toUpperCase(), body });
      buckets.delete(name);
    }

    const remaining = [...buckets.keys()].sort((a, b) => a.localeCompare(b));
    for (const name of remaining) {
      const fs = buckets.get(name);
      if (!fs?.length) continue;
      const body = this.flags(sortFlags(fs));
      if (body) out.push({ header: name.toUpperCase(), body });
    }

    return out;
  }

  private seeAlsoBody(cmd: Command.Loadable): string | undefined {
    const ids = (cmd as CommandWithSeeAlso).seeAlso;
    if (!ids?.length) return undefined;
    const lines = ids.map(
      (id: string) => `${this.config.bin} ${id.replace(/:/g, this.config.topicSeparator)}`,
    );
    return this.wrap(lines.join("\n\n"));
  }

  public override sections() {
    const usageHeader = this.opts.usageHeader || "USAGE";
    const sections = [
      {
        generate: (_ctx: HelpGenCtx, header: HelpGenHeader) => {
          void _ctx;
          void header;
          return this.usage();
        },
        header: usageHeader,
      },
      {
        generate: ({ args }: HelpGenCtx, header: HelpGenHeader) => [
          { body: this.args(args), header },
        ],
        header: "ARGUMENTS",
      },
      {
        generate: (_ctx: HelpGenCtx, header: HelpGenHeader) => {
          void _ctx;
          void header;
          return this.description();
        },
        header: "DESCRIPTION",
      },
      {
        generate: ({ cmd }: HelpGenCtx, header: HelpGenHeader) => {
          void header;
          return this.examples(cmd.examples as Command.Example[] | string | undefined);
        },
        header: "EXAMPLES",
      },
      {
        generate: ({ flags }: HelpGenCtx, header: HelpGenHeader) => {
          void header;
          return compactSections(
            this.flagHelpSections(flags).map((s) => ({ body: s.body, header: s.header })),
          );
        },
        header: "FLAGS",
      },
      {
        generate: ({ cmd }: HelpGenCtx, header: HelpGenHeader) => {
          void header;
          return this.seeAlsoBody(cmd);
        },
        header: "SEE ALSO",
      },
      {
        generate: ({ cmd }: HelpGenCtx, header: HelpGenHeader) => {
          void header;
          return this.aliases(cmd.aliases);
        },
        header: "ALIASES",
      },
      {
        generate: ({ flags }: HelpGenCtx, header: HelpGenHeader) => {
          void header;
          return this.flagsDescriptions(flags);
        },
        header: "FLAG DESCRIPTIONS",
      },
    ];

    const allowed = this.opts.sections?.map((s) => s.toLowerCase());
    return sections.filter(({ header }) => !allowed || allowed.includes(header.toLowerCase()));
  }
}

export default class ObjectifiedHelp extends Help {
  public CommandHelpClass = ObjectifiedCommandHelp;

  public constructor(
    config: ConstructorParameters<typeof Help>[0],
    opts: ConstructorParameters<typeof Help>[1] = {},
  ) {
    const argv = process.argv.slice(2);
    const stripAnsi = helpShouldStripAnsi(opts.stripAnsi, argv);
    super(config, { ...opts, stripAnsi });
  }

  public formatRoot(): string {
    return `${super.formatRoot()}\n\n${this.section("GLOBAL FLAGS", this.wrap(GLOBAL_FLAGS_BODY))}`;
  }
}
