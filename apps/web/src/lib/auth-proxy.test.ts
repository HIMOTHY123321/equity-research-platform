import { describe, expect, it } from "vitest";

import { secondsUntilJwtExpiry } from "@/lib/auth-proxy";

function makeToken(payload: Record<string, unknown>): string {
  const base64Url = (obj: object) =>
    Buffer.from(JSON.stringify(obj)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${base64Url({ alg: "HS256", typ: "JWT" })}.${base64Url(payload)}.fake-signature`;
}

describe("secondsUntilJwtExpiry (Phase 19.3)", () => {
  it("returns a positive integer for a token that expires in the future", () => {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    const seconds = secondsUntilJwtExpiry(makeToken({ exp }));
    expect(seconds).not.toBeNull();
    expect(seconds).toBeGreaterThan(3590);
    expect(seconds).toBeLessThanOrEqual(3600);
  });

  it("returns null for a token that has already expired", () => {
    const exp = Math.floor(Date.now() / 1000) - 10;
    expect(secondsUntilJwtExpiry(makeToken({ exp }))).toBeNull();
  });

  it("returns null when the payload has no exp claim", () => {
    expect(secondsUntilJwtExpiry(makeToken({ sub: "user-1" }))).toBeNull();
  });

  it("returns null for a malformed token (wrong number of segments)", () => {
    expect(secondsUntilJwtExpiry("not-a-jwt")).toBeNull();
  });

  it("returns null for a token whose payload segment is not valid JSON", () => {
    expect(secondsUntilJwtExpiry("header.not-valid-base64url-json.sig")).toBeNull();
  });
});
