import { describe, expect, it } from "vitest";
import { LineConfigSchema } from "./config-schema.js";

describe("LineConfigSchema", () => {
  it('rejects dmPolicy="open" without wildcard allowFrom', () => {
    const result = LineConfigSchema.safeParse({
      channelAccessToken: "token",
      channelSecret: "secret",
      dmPolicy: "open",
    });

    expect(result.success).toBe(false);
    if (result.success) {
      throw new Error("expected dmPolicy open without wildcard allowFrom to fail validation");
    }
    expect(result.error.issues).toEqual([
      expect.objectContaining({
        path: ["allowFrom"],
        message: 'channels.line.dmPolicy="open" requires channels.line.allowFrom to include "*"',
      }),
    ]);
  });

  it('accepts dmPolicy="open" with wildcard allowFrom', () => {
    const result = LineConfigSchema.safeParse({
      channelAccessToken: "token",
      channelSecret: "secret",
      dmPolicy: "open",
      allowFrom: ["*"],
    });

    expect(result.success).toBe(true);
  });

  it('rejects account dmPolicy="open" without wildcard allowFrom', () => {
    const result = LineConfigSchema.safeParse({
      accounts: {
        work: {
          channelAccessToken: "token",
          channelSecret: "secret",
          dmPolicy: "open",
        },
      },
    });

    expect(result.success).toBe(false);
    if (result.success) {
      throw new Error(
        "expected account dmPolicy open without wildcard allowFrom to fail validation",
      );
    }
    expect(result.error.issues).toEqual([
      expect.objectContaining({
        path: ["accounts", "work", "allowFrom"],
        message: 'channels.line.dmPolicy="open" requires channels.line.allowFrom to include "*"',
      }),
    ]);
  });
});
