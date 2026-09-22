"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Overview", symbolAware: true },
  { href: "/research", label: "Research Lab", symbolAware: true },
  { href: "/forecasts", label: "Forecast Lab", symbolAware: true },
  { href: "/reports", label: "Reports", symbolAware: false },
  { href: "/watchlist", label: "Watchlist", symbolAware: false },
];

function TopNavInner() {
  const pathname = usePathname();
  // (#9) The current page's `?symbol=` (if any) is carried onto every
  // other symbol-aware page's nav link -- otherwise clicking "Forecast
  // Lab" from Overview?symbol=NVDA would silently drop back to the
  // hardcoded default, defeating cross-page persistence entirely.
  const symbol = useSearchParams().get("symbol");

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
                className={active ? "text-foreground" : "hover:text-foreground"}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
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
