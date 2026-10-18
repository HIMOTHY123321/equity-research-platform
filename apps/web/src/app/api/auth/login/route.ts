import type { NextRequest } from "next/server";

import { proxyCredentialedAuthRequest } from "@/lib/auth-proxy";

export async function POST(request: NextRequest) {
  return proxyCredentialedAuthRequest(request, "/api/auth/login");
}
