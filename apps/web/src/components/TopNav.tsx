"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { useUnreadAlertCount } from "@/hooks/useAlerts";
import { useAuth } from "@/lib/auth-context";

const NAV_ITEMS = [
  { href: "/", label: "Overview", symbolAware: true },
  { href: "/opportunities", label: "Opportunities", symbolAware: false },
  { href: "/research", label: "Research Lab", symbolAware: true },
  { href: "/forecasts", label: "Forecast Lab", symbolAware: true },
  { href: "/reports", label: "Reports", symbolAware: false },
  { href: "/watchlist", label: "Watchlist", symbolAware: false },
  { href: "/scanner", label: "Scanner", symbolAware: false },
  { href: "/alerts", label: "Alerts", symbolAware: false },
  { href: "/long-term-research", label: "Long-Term Research", symbolAware: false },
  { href: "/validation", label: "Validation Lab", symbolAware: false },
  { href: "/glossary", label: "Glossary", symbolAware: false },
];

/** Phase 16.1 (§1/§9): account/session state visible in UI -- a signed-in
 * user sees their email and a Sign out control; a signed-out visitor sees
 * a Sign in link (the proxy already redirects them to /login before they
 * can reach a protected page, but /login and /signup themselves render
 * TopNav-less layouts, so this only ever shows up on product pages). */
function AccountMenu() {
  const { user, state, logout } = useAuth();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  if (state === "loading") return null;

  if (state !== "signed-in" || !user) {
    return (
      <Link href="/login" className="text-xs text-muted hover:text-foreground">
        Sign in
      </Link>
    );
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
      router.push("/login");
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="flex items-center gap-3 text-xs text-muted">
      <Link href="/settings" className="hover:text-foreground" title={user.email}>
        {user.email}
      </Link>
      <button
        type="button"
        onClick={handleSignOut}
        disabled={signingOut}
        className="hover:text-foreground disabled:opacity-60"
      >
        Sign out
      </button>
    </div>
  );
}

function TopNavInner() {
  const pathname = usePathname();
  // (#9) The current page's `?symbol=` (if any) is carried onto every
  // other symbol-aware page's nav link -- otherwise clicking "Forecast
  // Lab" from Overview?symbol=NVDA would silently drop back to the
  // hardcoded default, defeating cross-page persistence entirely.
  const symbol = useSearchParams().get("symbol");
  // §18: unobtrusive -- a small count badge, no flashing/animation.
  const unreadAlertCount = useUnreadAlertCount();

  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-sm font-semibold tracking-widest text-foreground">
            AI MARKET DESK
          </span>
          <span className="text-xs text-muted">research &middot; backtesting &middot; paper trading</span>
        </div>
        <nav className="flex gap-5 text-xs text-muted">
          {NAV_ITEMS.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname?.startsWith(item.href);
            const href = item.symbolAware && symbol ? `${item.href}?symbol=${symbol}` : item.href;
            return (
              <Link
                key={item.href}
                href={href}
                className={`flex items-center gap-1 ${active ? "text-foreground" : "hover:text-foreground"}`}
              >
                {item.label}
                {item.href === "/alerts" && unreadAlertCount > 0 && " "}
                {item.href === "/alerts" && unreadAlertCount > 0 && (
                  <span className="rounded-full bg-accent/20 px-1.5 text-[10px] text-accent">
                    {unreadAlertCount}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
        <AccountMenu />
      </div>
    </header>
  );
}

export function TopNav() {
  return (
    <Suspense fallback={null}>
      <TopNavInner />
    </Suspense>
  );
}
