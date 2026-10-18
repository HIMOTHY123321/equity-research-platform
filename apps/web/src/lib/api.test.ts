import { afterEach, describe, expect, it, vi } from "vitest";

import { getCurrentUser, login, logout, signup } from "@/lib/api";

const SAMPLE_USER = {
  id: "u1",
  email: "trader@example.com",
  status: "active",
  role: "user",
  plan: "free",
  timezone: "America/New_York",
  created_at: "2026-01-01T00:00:00Z",
};

describe("lib/api auth calls (Phase 19.3: same-origin, never cross-origin)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("login calls the same-origin /api/auth/login path, never NEXT_PUBLIC_API_URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ user: SAMPLE_USER }), { status: 200 }));

    const user = await login("trader@example.com", "hunter2hunter2");

    expect(user.email).toBe("trader@example.com");
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({ method: "POST" }));
  });

  it("signup calls the same-origin /api/auth/signup path", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ user: SAMPLE_USER }), { status: 201 }));

    await signup("trader@example.com", "hunter2hunter2");

    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/signup", expect.objectContaining({ method: "POST" }));
  });

  it("logout calls the same-origin /api/auth/logout path", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    await logout();

    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST" }));
  });

  it("getCurrentUser calls the same-origin /api/auth/me path and resolves null on 401", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://ai-market-desk.onrender.com");
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 }));

    const user = await getCurrentUser();

    expect(user).toBeNull();
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/me", expect.anything());
  });

  it("getCurrentUser resolves the user on success", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify(SAMPLE_USER), { status: 200 }));

    const user = await getCurrentUser();

    expect(user?.email).toBe("trader@example.com");
  });
});
