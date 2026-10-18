import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME, clearSessionCookie, getBackendBaseUrl } from "@/lib/auth-proxy";

export async function POST(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (token) {
    try {
      await fetch(`${getBackendBaseUrl()}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
    } catch {
      // Best-effort server-side revocation -- logout must always succeed
      // from the browser's point of view (matches the backend's own
      // contract in app.api.routes.auth.logout_route), so the frontend
      // cookie below is cleared unconditionally regardless.
    }
  }
  const response = new NextResponse(null, { status: 204 });
  clearSessionCookie(response);
  return response;
}
