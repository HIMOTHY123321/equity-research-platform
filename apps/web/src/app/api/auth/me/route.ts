import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME, getBackendBaseUrl } from "@/lib/auth-proxy";

export async function GET(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${getBackendBaseUrl()}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Authentication service unavailable" }, { status: 502 });
  }

  const payload = await backendResponse.json().catch(() => null);
  return NextResponse.json(payload, { status: backendResponse.status });
}
