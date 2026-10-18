import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME, getBackendBaseUrl } from "@/lib/auth-proxy";

/**
 * Phase 19.4: general same-origin REST proxy for the deployed frontend.
 *
 * Phase 19.3 fixed login/signup/logout/me, but every OTHER backend call in
 * lib/api.ts still went straight from the browser to the backend's own
 * onrender.com host, cross-origin -- which cannot carry the `amd_session`
 * cookie the frontend now mints for itself (see src/lib/auth-proxy.ts for
 * the full explanation of why not). This is the general-purpose follow-up:
 * one catch-all Route Handler that every normal REST call -- watchlist,
 * market data, research, decisions, alerts, etc. -- is proxied through
 * instead of writing a dedicated route per endpoint.
 *
 * browser --> /api/backend/api/<whatever> (this file, same-origin)
 *         --> NEXT_PUBLIC_API_URL/api/<whatever> (server-to-server, no
 *             CORS, no cross-site cookie problem at all)
 *
 * The incoming `amd_session` cookie (frontend-domain, HttpOnly, never
 * touched by client JS) is read here, server-side, and forwarded to the
 * backend as `Authorization: Bearer <token>` -- exactly the form
 * app.auth.dependencies.get_current_user already accepts as a fallback to
 * its own cookie (an explicit header always wins there), so no backend
 * change was needed for this to work.
 *
 * This is REST only. The live WebSocket (/api/live/stream) is a
 * completely separate transport and is NOT routed through this file --
 * see the Phase 19.4 report for why, and what (if anything) that needs.
 */

// Headers that are either meaningless/incorrect to forward across a
// server-to-server hop (connection-management headers a proxy must set
// for itself, never copy) or are handled explicitly elsewhere in this
// file (cookie -> Authorization on the way in; Set-Cookie dropped on the
// way out) -- never blindly forwarded in either direction.
const NEVER_FORWARD_REQUEST_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  "cookie",
]);

const NEVER_FORWARD_RESPONSE_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "content-length",
  "content-encoding",
  // The backend's own Set-Cookie (host-only to its own onrender.com
  // domain -- see the module docstring above) is never copied onto the
  // frontend's response; the only cookie this app's domain ever gets is
  // the one src/lib/auth-proxy.ts mints via the dedicated auth routes.
  "set-cookie",
]);

const METHODS_WITHOUT_A_BODY = new Set(["GET", "HEAD"]);

// Per the Fetch spec, a Response may never carry a body alongside one of
// these "null body" statuses -- the backend legitimately returns 204 for
// e.g. DELETE /api/watchlist/symbols/{ticker} and POST /api/auth/logout,
// and constructing `new NextResponse(buffer, { status: 204 })` throws
// even when that buffer is empty.
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

async function proxyToBackend(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const backendPath = `/${path.join("/")}`;
  const targetUrl = `${getBackendBaseUrl()}${backendPath}${request.nextUrl.search}`;

  const forwardHeaders = new Headers();
  for (const [name, value] of request.headers) {
    if (NEVER_FORWARD_REQUEST_HEADERS.has(name.toLowerCase())) continue;
    forwardHeaders.set(name, value);
  }
  const sessionToken = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (sessionToken) {
    forwardHeaders.set("Authorization", `Bearer ${sessionToken}`);
  } else {
    // Never forward a browser-supplied Authorization header as an
    // ambient credential -- this app's own client never sends one (the
    // session lives only in the HttpOnly cookie), so a present header can
    // only be a stray/forged one.
    forwardHeaders.delete("authorization");
  }

  const method = request.method;
  const body = METHODS_WITHOUT_A_BODY.has(method) ? undefined : await request.arrayBuffer();

  let backendResponse: Response;
  try {
    backendResponse = await fetch(targetUrl, {
      method,
      headers: forwardHeaders,
      body,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json({ detail: "Backend service unavailable" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  for (const [name, value] of backendResponse.headers) {
    if (NEVER_FORWARD_RESPONSE_HEADERS.has(name.toLowerCase())) continue;
    responseHeaders.set(name, value);
  }

  const responseBody = NULL_BODY_STATUSES.has(backendResponse.status)
    ? null
    : await backendResponse.arrayBuffer();
  return new NextResponse(responseBody, { status: backendResponse.status, headers: responseHeaders });
}

export {
  proxyToBackend as GET,
  proxyToBackend as POST,
  proxyToBackend as PUT,
  proxyToBackend as PATCH,
  proxyToBackend as DELETE,
  proxyToBackend as HEAD,
};
