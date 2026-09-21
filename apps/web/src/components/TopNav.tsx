"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/research", label: "Research Lab" },
  { href: "/forecasts", label: "Forecast Lab" },
  { href: "/reports", label: "Reports" },
  { href: "/watchlist", label: "Watchlist" },
];

export function TopNav() {
  const pathname = usePathname();

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
            return (
              <Link
                key={item.href}
                href={item.href}
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
