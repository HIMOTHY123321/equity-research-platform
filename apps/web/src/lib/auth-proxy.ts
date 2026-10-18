import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Phase 19.3: same-origin authentication proxy for the deployed frontend.
 *
 * The Render-deployed backend's own Set-Cookie for `amd_session` has no
 * Domain attribute (by design -- see app.auth.cookies on the backend), so
 * it is host-only to the backend's own onrender.com subdomain. A browser
 * on the FRONTEND's different onrender.com subdomain can never see that
 * cookie no matter what `credentials: "include"` does -- cookies are
 * scoped by the exact host they were set on, not by CORS policy. Sharing
 * it via `Domain=.onrender.com` is deliberately not done either: that
 * would hand the session cookie to every other app on Render's shared
 * wildcard domain, not just this project's own backend.
 *
 * The fix: login/signup/logout/me are never called by browser JS directly
 * against the backend. They go through the same-origin Next.js Route
 * Handlers in src/app/api/auth/*\/route.ts instead, which make the real
 * backend call server-side (plain server-to-server HTTP -- no CORS, no
 * cross-site cookie problem at all) and mint a SEPARATE `amd_session`
 * cookie scoped to the frontend's own domain. The raw JWT is never placed
 * in a response body a browser's JS can read -- only ever in an HttpOnly
 * Set-Cookie header, exactly like the backend's own cookie.
 *
 * Every other backend endpoint is unaffected by this file and is still
 * called directly, cross-origin, via lib/api.ts's `getApiBaseUrl()` --
 * those calls do not carry this cookie either (a known, separate
 * limitation; see the Phase 19.3 report for why fixing that is out of
 * scope here).
 */

export const SESSION_COOKIE_NAME = "amd_session";

export function getBackendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

function base64UrlDecode(input: string): Buffer {
  return Buffer.from(input.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

/** Reads the JWT's own `exp` claim (already verified once by the backend
 * that just issued it over this trusted server-to-server call) so the
 * frontend's cookie expires at exactly the same instant as the backend's
 * session, without duplicating `access_token_ttl_minutes` as a second
 * magic number here. Returns null for a malformed token -- callers treat
 * that as a hard failure, never a silent default max-age. */
export function secondsUntilJwtExpiry(token: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(base64UrlDecode(parts[1]).toString("utf-8")) as { exp?: number };
    if (typeof payload.exp !== "number") return null;
    const seconds = Math.floor(payload.exp - Date.now() / 1000);
    return seconds > 0 ? seconds : null;
  } catch {
    return null;
  }
}

function sessionCookieBaseAttributes() {
  return {
    httpOnly: true,
    path: "/",
    sameSite: "lax" as const,
    // Secure outside local development only -- matches the backend's own
    // `settings.is_production` gate on this same cookie
    // (app.auth.cookies.set_session_cookie), for the same reason: `next
    // dev` serves plain HTTP, where a browser silently drops a Secure
    // cookie entirely.
    secure: process.env.NODE_ENV === "production",
  };
}

export function setSessionCookie(response: NextResponse, token: string, maxAgeSeconds: number): void {
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    ...sessionCookieBaseAttributes(),
    maxAge: maxAgeSeconds,
  });
}

export function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE_NAME, "", {
    ...sessionCookieBaseAttributes(),
    maxAge: 0,
  });
}

/** Best-effort passthrough of the real client's address for the
 * backend's own per-IP auth rate limiter (app.rate_limiting.auth_rate_
 * limit) -- a server-to-server call would otherwise make every browser's
 * login attempt look like it came from this Next.js server's own egress
 * IP. The backend does not currently read this header (it keys on the
 * raw TCP peer -- see app/rate_limiting.py), so this is forward-looking
 * only until the backend is updated to honor it; a known, documented
 * limitation rather than an assumption that it already works. */
function forwardedForHeader(request: NextRequest): string | null {
  return request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip");
}

type BackendAuthPayload = {
  access_token?: unknown;
  user?: unknown;
  detail?: unknown;
};

/** Shared implementation for /api/auth/login and /api/auth/signup --
 * both are "send credentials, get back {access_token, user}, mint a
 * frontend cookie, and NEVER put the raw token in the JSON body a
 * browser's JS can read" with no other differences. */
export async function proxyCredentialedAuthRequest(
  request: NextRequest,
  backendPath: string,
): Promise<NextResponse> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  const forwardedFor = forwardedForHeader(request);
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${getBackendBaseUrl()}${backendPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(forwardedFor ? { "X-Forwarded-For": forwardedFor } : {}),
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Authentication service unavailable" }, { status: 502 });
  }

  const payload = (await backendResponse.json().catch(() => null)) as BackendAuthPayload | null;

  if (!backendResponse.ok) {
    // The backend's own error detail (invalid credentials, email already
    // registered, rate limited, ...) is forwarded verbatim -- there is
    // never a token on an error response to worry about exposing.
    return NextResponse.json(payload ?? { detail: "Authentication failed" }, { status: backendResponse.status });
  }

  const accessToken = payload?.access_token;
  const user = payload?.user;
  if (typeof accessToken !== "string" || !user) {
    return NextResponse.json({ detail: "Malformed response from authentication service" }, { status: 502 });
  }
  const maxAgeSeconds = secondsUntilJwtExpiry(accessToken);
  if (maxAgeSeconds === null) {
    return NextResponse.json({ detail: "Malformed response from authentication service" }, { status: 502 });
  }

  // `user` only -- `access_token` is deliberately never included in a
  // response body. The frontend never needs it: the cookie below is
  // HttpOnly, and every subsequent proxied call reads it server-side,
  // never from client-readable JSON.
  const response = NextResponse.json({ user }, { status: backendResponse.status });
  setSessionCookie(response, accessToken, maxAgeSeconds);
  return response;
}
