import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

function makeToken(exp: number): string {
  const base64Url = (obj: object) =>
    Buffer.from(JSON.stringify(obj)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${base64Url({ alg: "HS256", typ: "JWT" })}.${base64Url({ sub: "user-1", exp })}.fake-signature`;
}

function postLoginRequest(body: unknown) {
  return new NextRequest("http://frontend.onrender.com/api/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/login (Phase 19.3 same-origin auth proxy)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("mints a frontend-domain amd_session cookie and never exposes the raw token in the body", async () => {
    const token = makeToken(Math.floor(Date.now() / 1000) + 86400);
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: token,
          user: { id: "u1", email: "trader@example.com", status: "active", role: "user" },
        }),
        { status: 200 },
      ),
    );

    const response = await POST(postLoginRequest({ email: "trader@example.com", password: "hunter2hunter2" }));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.user.email).toBe("trader@example.com");
    expect(body.access_token).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain(token);

    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("amd_session=");
    expect(setCookie).toContain(token);
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("path=/");
    expect(setCookie.toLowerCase()).toContain("samesite=lax");
  });

  it("calls the backend at NEXT_PUBLIC_API_URL, never a hard-coded host", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const token = makeToken(Math.floor(Date.now() / 1000) + 3600);
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: token, user: { id: "u1" } }), { status: 200 }),
    );

    await POST(postLoginRequest({ email: "a@example.com", password: "password123" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "https://ai-market-desk.onrender.com/api/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("forwards the backend's error status and detail verbatim on invalid credentials", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Incorrect email or password" }), { status: 401 }),
    );

    const response = await POST(postLoginRequest({ email: "a@example.com", password: "wrong" }));

    expect(response.status).toBe(401);
    const body = await response.json();
    expect(body.detail).toBe("Incorrect email or password");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("never sets a cookie when the backend response is malformed (no access_token)", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ user: { id: "u1" } }), { status: 200 }),
    );

    const response = await POST(postLoginRequest({ email: "a@example.com", password: "password123" }));

    expect(response.status).toBe(502);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("returns 502 without a cookie when the backend is unreachable", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await POST(postLoginRequest({ email: "a@example.com", password: "password123" }));

    expect(response.status).toBe(502);
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
