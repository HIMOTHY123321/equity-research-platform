"""Development SymbolDirectory (#3): a curated, hand-maintained list of
common liquid US equities/ETFs -- NOT a claim of institutional security-
master completeness. Isolated entirely behind `SymbolDirectory` so a real
licensed reference-data source can replace this later with no caller
change. `popularity_rank` (lower = more liquid/prominent) is this static
list's own ordering, used only to break ties among equally-matched
results -- never a fabricated relevance score.
"""

from __future__ import annotations

from typing import Optional

from app.symbols.directory import SymbolDirectory
from app.symbols.schemas import AssetType, SymbolMatch

# (ticker, company/fund name, asset_type, popularity_rank)
_UNIVERSE: tuple[tuple[str, str, AssetType, int], ...] = (
    ("SPY", "SPDR S&P 500 ETF Trust", AssetType.ETF, 1),
    ("QQQ", "Invesco QQQ Trust (Nasdaq-100 ETF)", AssetType.ETF, 2),
    ("AAPL", "Apple Inc.", AssetType.EQUITY, 3),
    ("MSFT", "Microsoft Corporation", AssetType.EQUITY, 4),
    ("NVDA", "NVIDIA Corporation", AssetType.EQUITY, 5),
    ("AMZN", "Amazon.com, Inc.", AssetType.EQUITY, 6),
    ("GOOGL", "Alphabet Inc. (Class A)", AssetType.EQUITY, 7),
    ("GOOG", "Alphabet Inc. (Class C)", AssetType.EQUITY, 8),
    ("META", "Meta Platforms, Inc.", AssetType.EQUITY, 9),
    ("TSLA", "Tesla, Inc.", AssetType.EQUITY, 10),
    ("BRK.B", "Berkshire Hathaway Inc. (Class B)", AssetType.EQUITY, 11),
    ("AVGO", "Broadcom Inc.", AssetType.EQUITY, 12),
    ("JPM", "JPMorgan Chase & Co.", AssetType.EQUITY, 13),
    ("V", "Visa Inc.", AssetType.EQUITY, 14),
    ("MA", "Mastercard Incorporated", AssetType.EQUITY, 15),
    ("UNH", "UnitedHealth Group Incorporated", AssetType.EQUITY, 16),
    ("HD", "The Home Depot, Inc.", AssetType.EQUITY, 17),
    ("JNJ", "Johnson & Johnson", AssetType.EQUITY, 18),
    ("PG", "The Procter & Gamble Company", AssetType.EQUITY, 19),
    ("XOM", "Exxon Mobil Corporation", AssetType.EQUITY, 20),
    ("WMT", "Walmart Inc.", AssetType.EQUITY, 21),
    ("BAC", "Bank of America Corporation", AssetType.EQUITY, 22),
    ("DIS", "The Walt Disney Company", AssetType.EQUITY, 23),
    ("NFLX", "Netflix, Inc.", AssetType.EQUITY, 24),
    ("ADBE", "Adobe Inc.", AssetType.EQUITY, 25),
    ("CRM", "Salesforce, Inc.", AssetType.EQUITY, 26),
    ("ORCL", "Oracle Corporation", AssetType.EQUITY, 27),
    ("INTC", "Intel Corporation", AssetType.EQUITY, 28),
    ("AMD", "Advanced Micro Devices, Inc.", AssetType.EQUITY, 29),
    ("CSCO", "Cisco Systems, Inc.", AssetType.EQUITY, 30),
    ("PFE", "Pfizer Inc.", AssetType.EQUITY, 31),
    ("KO", "The Coca-Cola Company", AssetType.EQUITY, 32),
    ("PEP", "PepsiCo, Inc.", AssetType.EQUITY, 33),
    ("MRK", "Merck & Co., Inc.", AssetType.EQUITY, 34),
    ("ABBV", "AbbVie Inc.", AssetType.EQUITY, 35),
    ("TMO", "Thermo Fisher Scientific Inc.", AssetType.EQUITY, 36),
    ("ABT", "Abbott Laboratories", AssetType.EQUITY, 37),
    ("COST", "Costco Wholesale Corporation", AssetType.EQUITY, 38),
    ("TXN", "Texas Instruments Incorporated", AssetType.EQUITY, 39),
    ("QCOM", "QUALCOMM Incorporated", AssetType.EQUITY, 40),
    ("IBM", "International Business Machines Corporation", AssetType.EQUITY, 41),
    ("GE", "GE Aerospace", AssetType.EQUITY, 42),
    ("CAT", "Caterpillar Inc.", AssetType.EQUITY, 43),
    ("BA", "The Boeing Company", AssetType.EQUITY, 44),
    ("MCD", "McDonald's Corporation", AssetType.EQUITY, 45),
    ("NKE", "NIKE, Inc.", AssetType.EQUITY, 46),
    ("SBUX", "Starbucks Corporation", AssetType.EQUITY, 47),
    ("GS", "The Goldman Sachs Group, Inc.", AssetType.EQUITY, 48),
    ("MS", "Morgan Stanley", AssetType.EQUITY, 49),
    ("AXP", "American Express Company", AssetType.EQUITY, 50),
    ("VZ", "Verizon Communications Inc.", AssetType.EQUITY, 51),
    ("T", "AT&T Inc.", AssetType.EQUITY, 52),
    ("UPS", "United Parcel Service, Inc.", AssetType.EQUITY, 53),
    ("LOW", "Lowe's Companies, Inc.", AssetType.EQUITY, 54),
    ("UNP", "Union Pacific Corporation", AssetType.EQUITY, 55),
    ("RTX", "RTX Corporation", AssetType.EQUITY, 56),
    ("MDT", "Medtronic plc", AssetType.EQUITY, 57),
    ("GILD", "Gilead Sciences, Inc.", AssetType.EQUITY, 58),
    ("ISRG", "Intuitive Surgical, Inc.", AssetType.EQUITY, 59),
    ("NOW", "ServiceNow, Inc.", AssetType.EQUITY, 60),
    ("LMT", "Lockheed Martin Corporation", AssetType.EQUITY, 61),
    ("DE", "Deere & Company", AssetType.EQUITY, 62),
    ("BLK", "BlackRock, Inc.", AssetType.EQUITY, 63),
    ("C", "Citigroup Inc.", AssetType.EQUITY, 64),
    ("SCHW", "The Charles Schwab Corporation", AssetType.EQUITY, 65),
    ("CVX", "Chevron Corporation", AssetType.EQUITY, 66),
    ("MU", "Micron Technology, Inc.", AssetType.EQUITY, 67),
    ("PANW", "Palo Alto Networks, Inc.", AssetType.EQUITY, 68),
    ("SPCX", "Space Exploration Technologies Corp. (illustrative dev symbol)", AssetType.EQUITY, 200),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust", AssetType.ETF, 101),
    ("IWM", "iShares Russell 2000 ETF", AssetType.ETF, 102),
    ("VOO", "Vanguard S&P 500 ETF", AssetType.ETF, 103),
    ("VTI", "Vanguard Total Stock Market ETF", AssetType.ETF, 104),
    ("GLD", "SPDR Gold Shares", AssetType.ETF, 105),
    ("XLF", "Financial Select Sector SPDR Fund", AssetType.ETF, 106),
    ("XLE", "Energy Select Sector SPDR Fund", AssetType.ETF, 107),
    ("XLK", "Technology Select Sector SPDR Fund", AssetType.ETF, 108),
    ("ARKK", "ARK Innovation ETF", AssetType.ETF, 109),
    ("TQQQ", "ProShares UltraPro QQQ", AssetType.ETF, 110),
)


def _match_tier(query_upper: str, query_lower: str, ticker: str, name: str) -> Optional[int]:
    if ticker == query_upper:
        return 1
    if ticker.startswith(query_upper):
        return 2
    if name.lower().startswith(query_lower):
        return 3
    if query_lower in name.lower():
        return 4
    return None


class StaticSymbolDirectory(SymbolDirectory):
    def __init__(self, universe: tuple[tuple[str, str, AssetType, int], ...] = _UNIVERSE) -> None:
        self._universe = universe
        self._by_ticker = {
            ticker: (ticker, name, asset_type, rank) for ticker, name, asset_type, rank in universe
        }

    def search(
        self, query: str, *, watchlist_tickers: Optional[list[str]] = None, limit: int = 20
    ) -> list[SymbolMatch]:
        query = query.strip()
        if not query:
            return []
        query_upper = query.upper()
        query_lower = query.lower()
        watchlist_set = set(watchlist_tickers or [])

        scored: list[tuple[int, int, int, str, SymbolMatch]] = []
        for ticker, name, asset_type, rank in self._universe:
            tier = _match_tier(query_upper, query_lower, ticker, name)
            if tier is None:
                continue
            # (#3 tier 5) watchlist membership breaks ties within the same
            # match tier -- 0 sorts first, never changes whether it matched.
            watchlist_boost = 0 if ticker in watchlist_set else 1
            match = SymbolMatch(ticker=ticker, name=name, asset_type=asset_type, match_tier=tier)
            scored.append((tier, watchlist_boost, rank, ticker, match))
        scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
        return [row[4] for row in scored[:limit]]

    def get(self, ticker: str) -> Optional[SymbolMatch]:
        row = self._by_ticker.get(ticker.strip().upper())
        if row is None:
            return None
        t, name, asset_type, _rank = row
        return SymbolMatch(ticker=t, name=name, asset_type=asset_type, match_tier=1)


DEFAULT_SYMBOL_DIRECTORY = StaticSymbolDirectory()
