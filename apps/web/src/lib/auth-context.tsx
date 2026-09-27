"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { type AuthUser, getCurrentUser, login as apiLogin, logout as apiLogout, signup as apiSignup } from "@/lib/api";

type AuthState = "loading" | "signed-in" | "signed-out";

interface AuthContextValue {
  user: AuthUser | null;
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

// A component rendered without <AuthProvider> (most component-level unit
// tests -- they test one component in isolation, not the whole app tree)
// gets this default: permanently signed-out, never `loading`, and never
// attempts a network call. This is what keeps hooks like
// useUnreadAlertCount from ever hitting a real backend in tests that don't
// explicitly wrap in a provider -- see useAlerts.ts's own auth-state guard.
const DEFAULT_CONTEXT: AuthContextValue = {
  user: null,
  state: "signed-out",
  login: async () => {
    throw new Error("useAuth: no <AuthProvider> in the tree");
  },
  signup: async () => {
    throw new Error("useAuth: no <AuthProvider> in the tree");
  },
  logout: async () => {
    throw new Error("useAuth: no <AuthProvider> in the tree");
  },
  refresh: async () => {
    throw new Error("useAuth: no <AuthProvider> in the tree");
  },
};

const AuthContext = createContext<AuthContextValue>(DEFAULT_CONTEXT);

/**
 * Phase 16.1: the single source of truth for "who is signed in" on the
 * client. Never reads or writes the session token itself -- the token
 * lives only in the HttpOnly `amd_session` cookie the browser manages;
 * this provider just asks the backend "who am I" via `/api/auth/me`
 * (cookie sent automatically) and reacts to `amd:session-expired`
 * (dispatched by lib/api.ts on any 401) by clearing local state, which is
 * what drives the proxy/redirect-to-login flow on the next navigation.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [state, setState] = useState<AuthState>("loading");

  const refresh = useCallback(async () => {
    const current = await getCurrentUser();
    setUser(current);
    setState(current ? "signed-in" : "signed-out");
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setState("signed-out");
    };
    window.addEventListener("amd:session-expired", onExpired);
    return () => window.removeEventListener("amd:session-expired", onExpired);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const current = await apiLogin(email, password);
    setUser(current);
    setState("signed-in");
  }, []);

  const signup = useCallback(async (email: string, password: string) => {
    const current = await apiSignup(email, password);
    setUser(current);
    setState("signed-in");
  }, []);

  const logout = useCallback(async () => {
    await apiLogout().catch(() => undefined);
    setUser(null);
    setState("signed-out");
  }, []);

  return (
    <AuthContext.Provider value={{ user, state, login, signup, logout, refresh }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
