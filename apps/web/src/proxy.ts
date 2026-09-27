import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Phase 16.1 (§1): gates every product route on a genuinely valid session
 * -- not just cookie presence. Runs in the Node.js runtime (Next.js 16
 * default for proxy), so a plain HMAC-SHA256 check via node:crypto is
 * enough; no extra JWT dependency needed. `SESSION_JWT_SECRET` must match
 * the backend's `SECRET_KEY` (see apps/api/.env.example) -- both default
 * to the same obviously-fake development placeholder so local dev works
 * with zero extra configuration; production MUST override both to the
 * same real secret (see docs/deployment.md).
 *
 * This is intentionally a fast, self-contained signature+expiry check,
 * not a session-revocation check (that requires a DB round trip this
 * layer deliberately avoids) -- a revoked-but-unexpired session cookie
 * still passes this proxy, but the backend's own get_current_user (which
 * DOES check revocation) will 401 the first real API call, and lib/api.ts
 * reacts to that by clearing client auth state and sending the user back
 * to /login. Belt (fast client-side gate) and suspenders (authoritative
 * server-side check), never either alone.
 *
 * MUST live at src/proxy.ts, not the package root -- Next.js requires it
 * at the same level as `app`/`pages` (this project's `app` dir is under
 * `src`).
 */
const SESSION_COOKIE_NAME = "amd_session";
const DEV_SECRET = "insecure-development-secret-do-not-use-in-production";
const PUBLIC_PATHS = new Set(["/login", "/signup"]);

function base64UrlDecode(input: string): Buffer {
  return Buffer.from(input.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

function isValidSession(token: string, secret: string): boolean {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [headerB64, payloadB64, signatureB64] = parts;
  try {
    const expectedSignature = createHmac("sha256", secret).update(`${headerB64}.${payloadB64}`).digest();
    const actualSignature = base64UrlDecode(signatureB64);
    if (expectedSignature.length !== actualSignature.length) return false;
    if (!timingSafeEqual(expectedSignature, actualSignature)) return false;

    const payload = JSON.parse(base64UrlDecode(payloadB64).toString("utf-8")) as { exp?: number };
    if (typeof payload.exp !== "number") return false;
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const secret = process.env.SESSION_JWT_SECRET || DEV_SECRET;
  if (token && isValidSession(token, secret)) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname + request.nextUrl.search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};
