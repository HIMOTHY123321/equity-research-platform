import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

function meRequestWithCookie(token?: string) {
  return new NextRequest("http://frontend.onrender.com/api/auth/me", {
    headers: token ? { cookie: `amd_session=${token}` } : undefined,
  });
}

describe("GET /api/auth/me (Phase 19.3 same-origin auth proxy)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 401 immediately when there is no frontend session cookie, never calling the backend", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    const response = await GET(meRequestWithCookie());

    expect(response.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("forwards the cookie as a Bearer token and returns the backend's user payload", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "u1", email: "trader@example.com" }), { status: 200 }),
    );

    const response = await GET(meRequestWithCookie("session-token-abc"));

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/auth/me"),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer session-token-abc" }) }),
    );
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.email).toBe("trader@example.com");
  });

  it("forwards a 401 from the backend (e.g. revoked session) verbatim", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Session expired or revoked" }), { status: 401 }),
    );

    const response = await GET(meRequestWithCookie("stale-token"));

    expect(response.status).toBe(401);
  });

  it("returns 502 when the backend is unreachable", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await GET(meRequestWithCookie("some-token"));

    expect(response.status).toBe(502);
  });
});
