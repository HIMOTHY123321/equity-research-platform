import Link from "next/link";

export function TopNav() {
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
          <Link href="/" className="text-foreground hover:text-foreground">
            Overview
          </Link>
          <Link href="/research" className="hover:text-foreground">
            Research Lab
          </Link>
          <Link href="/forecasts" className="hover:text-foreground">
            Forecast Lab
          </Link>
          <span className="cursor-default">Reports</span>
          <span className="cursor-default">Watchlist</span>
        </nav>
      </div>
    </header>
  );
}
