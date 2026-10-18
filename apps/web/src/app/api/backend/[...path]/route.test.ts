import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

type NextRequestInit = ConstructorParameters<typeof NextRequest>[1];

function ctx(...path: string[]) {
  return { params: Promise.resolve({ path }) };
}

function req(url: string, init?: RequestInit) {
  return new NextRequest(url, init as NextRequestInit);
}

function withSessionCookie(token: string, init: RequestInit = {}): RequestInit {
  return { ...init, headers: { ...(init.headers as Record<string, string> | undefined), cookie: `amd_session=${token}` } };
}

describe("ALL /api/backend/[...path] (Phase 19.4 general REST proxy)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("proxies an authenticated GET (watchlist) and forwards the session as a Bearer token", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ ticker: "SPY" }]), { status: 200, headers: { "content-type": "application/json" } }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("session-token-abc")),
      ctx("api", "watchlist"),
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/watchlist"),
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ get: expect.any(Function) }),
      }),
    );
    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token-abc");

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual([{ ticker: "SPY" }]);
  });

  it("preserves query parameters", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response("[]", { status: 200 }));

    await GET(
      req(
        "http://frontend.onrender.com/api/backend/api/market/SPY/candles?timeframe=1h&limit=200",
        withSessionCookie("tok"),
      ),
      ctx("api", "market", "SPY", "candles"),
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/market/SPY/candles?timeframe=1h&limit=200"),
      expect.anything(),
    );
  });

  it("forwards a JSON POST body verbatim and preserves the backend's own status code", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ticker: "NVDA" }), { status: 201 }),
    );

    const response = await POST(
      req("http://frontend.onrender.com/api/backend/api/watchlist/symbols", {
        ...withSessionCookie("tok"),
        method: "POST",
        headers: { "content-type": "application/json", cookie: "amd_session=tok" },
        body: JSON.stringify({ ticker: "NVDA" }),
      }),
      ctx("api", "watchlist", "symbols"),
    );

    const [, init] = fetchSpy.mock.calls[0];
    const sentBody = Buffer.from(init?.body as ArrayBuffer).toString("utf-8");
    expect(sentBody).toBe(JSON.stringify({ ticker: "NVDA" }));
    expect(init?.method).toBe("POST");
    expect(response.status).toBe(201);
  });

  it("forwards a backend 401 verbatim (e.g. no/expired session)", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 }),
    );

    const response = await GET(req("http://frontend.onrender.com/api/backend/api/watchlist"), ctx("api", "watchlist"));

    expect(response.status).toBe(401);
    const body = await response.json();
    expect(body.detail).toBe("Not authenticated");
  });

  it("forwards a backend 403 verbatim", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/admin/anything", withSessionCookie("tok")),
      ctx("api", "admin", "anything"),
    );

    expect(response.status).toBe(403);
  });

  it("forwards a backend 404 verbatim", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unknown symbol: ZZZZ" }), { status: 404 }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/symbols/ZZZZ", withSessionCookie("tok")),
      ctx("api", "symbols", "ZZZZ"),
    );

    expect(response.status).toBe(404);
  });

  it("forwards a backend 500 verbatim without masking it as something else", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Internal Server Error" }), { status: 500 }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("tok")),
      ctx("api", "watchlist"),
    );

    expect(response.status).toBe(500);
  });

  it("never exposes the session token in the client-visible response", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ ticker: "SPY" }]), { status: 200 }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("super-secret-session-token")),
      ctx("api", "watchlist"),
    );

    const rawText = await response.text();
    expect(rawText).not.toContain("super-secret-session-token");
    expect(response.headers.get("authorization")).toBeNull();
  });

  it("makes an unauthenticated call (no cookie) without an Authorization header, letting the backend decide", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));

    await GET(req("http://frontend.onrender.com/api/backend/health"), ctx("health"));

    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
  });

  it("never forwards the backend's own Set-Cookie header onto the frontend's response", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response("{}", { status: 200, headers: { "set-cookie": "something_unrelated=1; Path=/" } }),
    );

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("tok")),
      ctx("api", "watchlist"),
    );

    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("never forwards the browser's Cookie header to the backend", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));

    await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("tok")),
      ctx("api", "watchlist"),
    );

    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("cookie")).toBeNull();
  });

  it("supports DELETE", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    const response = await DELETE(
      req("http://frontend.onrender.com/api/backend/api/watchlist/symbols/NVDA", {
        ...withSessionCookie("tok"),
        method: "DELETE",
      }),
      ctx("api", "watchlist", "symbols", "NVDA"),
    );

    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining("/api/watchlist/symbols/NVDA"), expect.objectContaining({ method: "DELETE" }));
    expect(response.status).toBe(204);
  });

  it("returns 502 when the backend is unreachable", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("tok")),
      ctx("api", "watchlist"),
    );

    expect(response.status).toBe(502);
  });

  it("calls the backend at NEXT_PUBLIC_API_URL, not a hard-coded host", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response("[]", { status: 200 }));

    await GET(
      req("http://frontend.onrender.com/api/backend/api/watchlist", withSessionCookie("tok")),
      ctx("api", "watchlist"),
    );

    expect(fetchSpy).toHaveBeenCalledWith("https://ai-market-desk.onrender.com/api/watchlist", expect.anything());
    vi.unstubAllEnvs();
  });
});
