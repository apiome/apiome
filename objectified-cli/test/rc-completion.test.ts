import { describe, expect, it } from "vitest";

import { COMPLETION_BEGIN, COMPLETION_END } from "../src/lib/completion/constants.js";
import {
  stripMarkedCompletionBlock,
  upsertMarkedCompletionBlock,
} from "../src/lib/completion/rc-file.js";

describe("completion rc markers", () => {
  it("upserts a new marked block", () => {
    const next = upsertMarkedCompletionBlock("echo hello\n", "body line");
    expect(next).toContain(COMPLETION_BEGIN);
    expect(next).toContain(COMPLETION_END);
    expect(next).toContain("body line");
    expect(next).toContain("echo hello");
  });

  it("replaces an existing marked block", () => {
    const first = upsertMarkedCompletionBlock("", "v1");
    const second = upsertMarkedCompletionBlock(first, "v2");
    expect(second.match(new RegExp(COMPLETION_BEGIN, "g"))?.length).toBe(1);
    expect(second).toContain("v2");
    expect(second).not.toContain("v1");
  });

  it("stripMarkedCompletionBlock removes only the marked region", () => {
    const wrapped = upsertMarkedCompletionBlock("before\n", "mid");
    const stripped = stripMarkedCompletionBlock(wrapped);
    expect(stripped).toContain("before");
    expect(stripped).not.toContain(COMPLETION_BEGIN);
    expect(stripped).not.toContain("mid");
  });
});
