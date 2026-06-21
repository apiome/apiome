import { describe, expect, it } from "vitest";

import {
  parseCompletionLine,
  tokenizeLine,
  tokenizeLineDetailed,
} from "../src/lib/interactive/tokenize.js";
import { classifyLine } from "../src/lib/interactive/repl.js";

describe("tokenizeLine", () => {
  it("splits plain words on whitespace", () => {
    expect(tokenizeLine("projects list")).toEqual(["projects", "list"]);
    expect(tokenizeLine("  hello   Ada  ")).toEqual(["hello", "Ada"]);
  });

  it("keeps double-quoted values as one token", () => {
    expect(tokenizeLine('projects create --name "My Project"')).toEqual([
      "projects",
      "create",
      "--name",
      "My Project",
    ]);
  });

  it("keeps single-quoted values literal", () => {
    expect(tokenizeLine("hello 'Ada Lovelace'")).toEqual(["hello", "Ada Lovelace"]);
  });

  it("honours backslash escapes inside and outside double quotes", () => {
    expect(tokenizeLine("hello a\\ b")).toEqual(["hello", "a b"]);
    expect(tokenizeLine('hello "a\\"b"')).toEqual(["hello", 'a"b']);
  });

  it("returns empty token list for blank input", () => {
    expect(tokenizeLine("")).toEqual([]);
    expect(tokenizeLine("   ")).toEqual([]);
  });
});

describe("tokenizeLineDetailed", () => {
  it("reports a trailing space (cursor starts a new word)", () => {
    expect(tokenizeLineDetailed("projects ").trailingSpace).toBe(true);
    expect(tokenizeLineDetailed("projects").trailingSpace).toBe(false);
  });

  it("reports an unterminated quote", () => {
    expect(tokenizeLineDetailed('hello "Ada').openQuote).toBe('"');
    expect(tokenizeLineDetailed("hello 'Ada").openQuote).toBe("'");
    expect(tokenizeLineDetailed('hello "Ada"').openQuote).toBeNull();
  });
});

describe("parseCompletionLine", () => {
  it("prepends the bin name and targets the empty word on a blank line", () => {
    expect(parseCompletionLine("", "objectified")).toEqual({
      words: ["objectified", ""],
      cword: 1,
      current: "",
      insideQuote: false,
    });
  });

  it("targets the partial token mid-word", () => {
    expect(parseCompletionLine("projects li", "objectified")).toEqual({
      words: ["objectified", "projects", "li"],
      cword: 2,
      current: "li",
      insideQuote: false,
    });
  });

  it("targets a fresh empty word after a trailing space", () => {
    expect(parseCompletionLine("projects ", "objectified")).toEqual({
      words: ["objectified", "projects", ""],
      cword: 2,
      current: "",
      insideQuote: false,
    });
  });

  it("flags completion inside an unterminated quote", () => {
    const parsed = parseCompletionLine('hello "Ada Lo', "objectified");
    expect(parsed.insideQuote).toBe(true);
  });
});

describe("classifyLine", () => {
  it("treats blank lines as empty", () => {
    expect(classifyLine("").kind).toBe("empty");
    expect(classifyLine("   ").kind).toBe("empty");
  });

  it("recognises exit words only as a lone token", () => {
    expect(classifyLine("exit").kind).toBe("exit");
    expect(classifyLine("quit").kind).toBe("exit");
    expect(classifyLine(":q").kind).toBe("exit");
    expect(classifyLine("EXIT").kind).toBe("exit");
    // `exit` with extra tokens is a normal command, not a builtin.
    expect(classifyLine("exit now").kind).toBe("run");
  });

  it("recognises clear", () => {
    expect(classifyLine("clear").kind).toBe("clear");
  });

  it("guards nested interactive/repl", () => {
    expect(classifyLine("interactive").kind).toBe("nested");
    expect(classifyLine("repl --json").kind).toBe("nested");
  });

  it("returns argv for runnable lines", () => {
    const result = classifyLine('projects create --name "My Project"');
    expect(result).toEqual({
      kind: "run",
      argv: ["projects", "create", "--name", "My Project"],
    });
  });
});
