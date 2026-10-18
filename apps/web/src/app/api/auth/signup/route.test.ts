import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

function makeToken(exp: number): string {
  const base64Url = (obj: object) =>
    Buffer.from(JSON.stringify(obj)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${base64Url({ alg: "HS256", typ: "JWT" })}.${base64Url({ sub: "user-1", exp })}.fake-signature`;
}

function postSignupRequest(body: unknown) {
  return new NextRequest("http://frontend.onrender.com/api/auth/signup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/signup (Phase 19.3 same-origin auth proxy)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("forwards the backend's 201 status and mints a frontend cookie, body has no token", async () => {
    const token = makeToken(Math.floor(Date.now() / 1000) + 86400);
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ access_token: token, user: { id: "u2", email: "new@example.com" } }),
        { status: 201 },
      ),
    );

    const response = await POST(postSignupRequest({ email: "new@example.com", password: "hunter2hunter2" }));

    expect(response.status).toBe(201);
    const body = await response.json();
    expect(body.user.email).toBe("new@example.com");
    expect(body.access_token).toBeUndefined();
    expect(response.headers.get("set-cookie")).toContain(token);
  });

  it("forwards a 409 conflict for an already-registered email without setting a cookie", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Email already registered" }), { status: 409 }),
    );

    const response = await POST(postSignupRequest({ email: "dup@example.com", password: "password123" }));

    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.detail).toBe("Email already registered");
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
