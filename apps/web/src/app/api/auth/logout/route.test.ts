import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

function logoutRequestWithCookie(token?: string) {
  return new NextRequest("http://frontend.onrender.com/api/auth/logout", {
    method: "POST",
    headers: token ? { cookie: `amd_session=${token}` } : undefined,
  });
}

describe("POST /api/auth/logout (Phase 19.3 same-origin auth proxy)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clears the frontend-domain amd_session cookie", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    const response = await POST(logoutRequestWithCookie("some-token"));

    expect(response.status).toBe(204);
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("amd_session=;");
    expect(setCookie.toLowerCase()).toContain("httponly");
  });

  it("forwards the session as a Bearer token so the backend actually revokes it", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    await POST(logoutRequestWithCookie("session-token-abc"));

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/auth/logout"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer session-token-abc" }),
      }),
    );
  });

  it("still clears the cookie (succeeds from the browser's point of view) even if the backend call fails", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await POST(logoutRequestWithCookie("some-token"));

    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toContain("amd_session=;");
  });

  it("clears the cookie even when no session cookie was present at all", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    const response = await POST(logoutRequestWithCookie());

    expect(response.status).toBe(204);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(response.headers.get("set-cookie")).toContain("amd_session=;");
  });
});
