import type {
  AnalogQueryResponse,
  AnalysisMode,
  BriefListItem,
  CandlesResponse,
  CatalystEvent,
  CatalystEventDetail,
  CatalystResearchQueryResponse,
  EvidencePacket,
  FeatureSnapshot,
  ForecastCategoryKind,
  ForecastOriginKind,
  ForecastOutcome,
  ForecastPerformanceResponse,
  ForwardForecast,
  ForwardValidationGateEvaluation,
  LedgerEntriesResponse,
  LiveStatusResponse,
  MarketReaction,
  MarketStructureSnapshot,
  NormalizedNewsArticle,
  ResearchBrief,
  ResearchQueryResponse,
  ResearchRun,
  ResearchRunSummary,
  ResearchSnapshot,
  SetupCandidate,
  SetupCatalystContext,
  SetupDetectionSnapshot,
  SnapshotComparison,
  SupportResistanceSnapshot,
  SymbolMatch,
  SymbolSearchResponse,
  Timeframe,
  UniverseReplayResponse,
  WatchlistSymbol,
  WhatsMovingResponse,
} from "@/lib/types";

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export type HealthStatus = {
  status: string;
  environment: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message = body?.detail ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function checkApiHealth(): Promise<HealthStatus | null> {
  try {
    return await request<HealthStatus>("/health");
  } catch {
    return null;
  }
}

export function getCandles(
  symbol: string,
  timeframe: Timeframe,
  limit = 200,
): Promise<CandlesResponse> {
  const params = new URLSearchParams({ timeframe, limit: String(limit) });
  return request<CandlesResponse>(`/api/market/${symbol}/candles?${params}`);
}

/** §5: the one source of truth for whether market data is genuinely
 * streaming vs. polled -- never inferred from freshness/age alone. */
export function getLiveStatus(): Promise<LiveStatusResponse> {
  return request<LiveStatusResponse>("/api/live/status");
}

/** (MARKET UX COMPLETION PASS #3) `watchlistTickers` only breaks ties
 * among already-matched results (ranking tier 5) -- never widens what
 * matches. Never falls back to SPY: an empty/no-match query returns an
 * empty result list, left to the caller to render as "no results". */
export function searchSymbols(query: string, watchlistTickers: string[] = []): Promise<SymbolSearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (watchlistTickers.length > 0) params.set("watchlist", watchlistTickers.join(","));
  return request<SymbolSearchResponse>(`/api/symbols/search?${params}`);
}

/** (#4) Resolves to `null` (never throws/falls back) when the ticker isn't
 * in the symbol directory -- the caller renders "Symbol not found". */
export async function getSymbol(ticker: string): Promise<SymbolMatch | null> {
  try {
    return await request<SymbolMatch>(`/api/symbols/${ticker}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function getWatchlist(): Promise<WatchlistSymbol[]> {
  return request<WatchlistSymbol[]>("/api/watchlist");
}

export function addWatchlistSymbol(ticker: string): Promise<WatchlistSymbol> {
  return request<WatchlistSymbol>("/api/watchlist/symbols", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });
}

export function removeWatchlistSymbol(ticker: string): Promise<void> {
  return request<void>(`/api/watchlist/symbols/${ticker}`, { method: "DELETE" });
}

export function getFeatures(symbol: string, timeframe: Timeframe): Promise<FeatureSnapshot> {
  const params = new URLSearchParams({ timeframe });
  return request<FeatureSnapshot>(`/api/market/${symbol}/features?${params}`);
}

export function getStructure(
  symbol: string,
  timeframe: Timeframe,
): Promise<MarketStructureSnapshot> {
  const params = new URLSearchParams({ timeframe });
  return request<MarketStructureSnapshot>(`/api/market/${symbol}/structure?${params}`);
}

export function getLevels(symbol: string, timeframe: Timeframe): Promise<SupportResistanceSnapshot> {
  const params = new URLSearchParams({ timeframe });
  return request<SupportResistanceSnapshot>(`/api/market/${symbol}/levels?${params}`);
}

export function getSetups(symbol: string, timeframe: Timeframe): Promise<SetupDetectionSnapshot> {
  const params = new URLSearchParams({ timeframe });
  return request<SetupDetectionSnapshot>(`/api/market/${symbol}/setups?${params}`);
}

// ---- Research engine (Phase 7) --------------------------------------------

export function postReplay(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<ResearchRun> {
  return request<{ run_id: string; status: string }>(`/api/research/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, timeframe, start, end }),
  }).then((res) => getResearchRun(res.run_id));
}

export function getResearchRun(runId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/research/runs/${runId}`);
}

export function getResearchRunSummary(runId: string): Promise<ResearchRunSummary> {
  return request<ResearchRunSummary>(`/api/research/runs/${runId}/summary`);
}

export function getResearchRunSetups(
  runId: string,
  params: { setupType?: string; state?: string; limit?: number } = {},
): Promise<LedgerEntriesResponse> {
  const query = new URLSearchParams();
  if (params.setupType) query.set("setup_type", params.setupType);
  if (params.state) query.set("state", params.state);
  query.set("limit", String(params.limit ?? 200));
  return request<LedgerEntriesResponse>(`/api/research/runs/${runId}/setups?${query}`);
}

export function listResearchRuns(limit = 20): Promise<ResearchRun[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  return request<ResearchRun[]>(`/api/research/runs?${params}`);
}

// ---- Research Intelligence (Phase 8) ---------------------------------------

export function postUniverseReplay(
  symbols: string[],
  timeframe: Timeframe,
  start: string,
  end: string,
): Promise<UniverseReplayResponse> {
  return request<UniverseReplayResponse>(`/api/research/universe-replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols, timeframe, start, end }),
  });
}

export interface ResearchQueryParams {
  runIds: string[];
  setupType?: string;
  direction?: string;
  qualificationState?: string;
  horizonBars?: number;
  seed?: number;
  partitionRatios?: boolean;
  favorableAtr?: number;
  adverseAtr?: number;
}

export function postResearchQuery(params: ResearchQueryParams): Promise<ResearchQueryResponse> {
  return request<ResearchQueryResponse>(`/api/research/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_ids: params.runIds,
      setup_type: params.setupType ?? null,
      direction: params.direction ?? null,
      qualification_state: params.qualificationState ?? null,
      horizon_bars: params.horizonBars ?? 5,
      seed: params.seed ?? 0,
      partition_ratios: params.partitionRatios ?? true,
      favorable_atr: params.favorableAtr ?? null,
      adverse_atr: params.adverseAtr ?? null,
    }),
  });
}

export function postAnalogQuery(
  queryCandidate: SetupCandidate,
  corpusRunIds: string[],
  topN?: number,
  includeCatalystContext?: boolean,
): Promise<AnalogQueryResponse> {
  return request<AnalogQueryResponse>(`/api/research/analogs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query_candidate: queryCandidate,
      corpus_run_ids: corpusRunIds,
      top_n: topN ?? null,
      include_catalyst_context: includeCatalystContext ?? false,
    }),
  });
}

export function listResearchSnapshots(limit = 50): Promise<ResearchSnapshot[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  return request<ResearchSnapshot[]>(`/api/research/snapshots?${params}`);
}

export function getResearchSnapshot(snapshotId: string): Promise<ResearchSnapshot> {
  return request<ResearchSnapshot>(`/api/research/snapshots/${snapshotId}`);
}

export function createResearchSnapshot(body: {
  label: string;
  research_run_ids: string[];
  config_hash: string;
  dataset_manifest: Record<string, unknown>;
  cohort_definition: Record<string, unknown>;
  filters: Record<string, unknown>;
  statistical_output: Record<string, unknown>;
  warning_flags: string[];
}): Promise<{ snapshot_id: string }> {
  return request<{ snapshot_id: string }>(`/api/research/snapshots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function compareResearchSnapshots(
  snapshotA: string,
  snapshotB: string,
): Promise<SnapshotComparison> {
  const params = new URLSearchParams({ snapshot_a: snapshotA, snapshot_b: snapshotB });
  return request<SnapshotComparison>(`/api/research/snapshots/compare?${params}`);
}

// ---- News / Catalyst Context engine (Phase 10) ------------------------------

export function getSymbolNews(symbol: string, days = 30): Promise<NormalizedNewsArticle[]> {
  const params = new URLSearchParams({ days: String(days) });
  return request<NormalizedNewsArticle[]>(`/api/news/${symbol}?${params}`);
}

export function getWhatsMoving(symbols: string[], days = 3): Promise<WhatsMovingResponse> {
  const params = new URLSearchParams({ symbols: symbols.join(","), days: String(days) });
  return request<WhatsMovingResponse>(`/api/news/market/whats-moving?${params}`);
}

export function getSymbolCatalysts(symbol: string, days = 30): Promise<CatalystEvent[]> {
  const params = new URLSearchParams({ days: String(days) });
  return request<CatalystEvent[]>(`/api/catalysts/${symbol}?${params}`);
}

export function getCatalystEvent(eventId: string): Promise<CatalystEventDetail> {
  return request<CatalystEventDetail>(`/api/catalysts/event/${eventId}`);
}

export function getCatalystReaction(
  eventId: string,
  symbol: string,
  timeframe: Timeframe,
): Promise<MarketReaction> {
  const params = new URLSearchParams({ symbol, timeframe });
  return request<MarketReaction>(`/api/catalysts/event/${eventId}/reaction?${params}`);
}

export function getSetupCatalystContext(
  candidate: SetupCandidate,
  lookbackDays = 5,
): Promise<SetupCatalystContext> {
  return request<SetupCatalystContext>(`/api/catalysts/setup-context`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate, lookback_days: lookbackDays }),
  });
}

export interface CatalystResearchQueryParams extends ResearchQueryParams {
  requireCatalyst?: boolean;
  catalystCategory?: string;
  catalystMaxHoursSince?: number;
  catalystRvolElevated?: boolean;
  compareToNoCatalyst?: boolean;
}

export function postCatalystResearchQuery(
  params: CatalystResearchQueryParams,
): Promise<CatalystResearchQueryResponse> {
  return request<CatalystResearchQueryResponse>(`/api/research/catalysts/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_ids: params.runIds,
      setup_type: params.setupType ?? null,
      direction: params.direction ?? null,
      qualification_state: params.qualificationState ?? null,
      horizon_bars: params.horizonBars ?? 5,
      seed: params.seed ?? 0,
      partition_ratios: params.partitionRatios ?? true,
      favorable_atr: params.favorableAtr ?? null,
      adverse_atr: params.adverseAtr ?? null,
      require_catalyst: params.requireCatalyst ?? false,
      catalyst_category: params.catalystCategory ?? null,
      catalyst_max_hours_since: params.catalystMaxHoursSince ?? null,
      catalyst_rvol_elevated: params.catalystRvolElevated ?? null,
      compare_to_no_catalyst: params.compareToNoCatalyst ?? false,
    }),
  });
}

// ---- AI Research Analyst (Phase 11) -----------------------------------------

export interface EvidencePacketParams {
  symbol: string;
  timeframe: string;
  setupId?: string;
  asOf?: string;
}

export function getEvidencePacket(params: EvidencePacketParams): Promise<EvidencePacket> {
  const query = new URLSearchParams({ timeframe: params.timeframe });
  if (params.setupId) query.set("setup_id", params.setupId);
  if (params.asOf) query.set("as_of", params.asOf);
  return request<EvidencePacket>(`/api/analysis/${params.symbol}/evidence?${query}`);
}

export interface ResearchBriefParams extends EvidencePacketParams {
  mode: AnalysisMode;
}

export function postResearchBrief(params: ResearchBriefParams): Promise<ResearchBrief> {
  const query = new URLSearchParams({ timeframe: params.timeframe, mode: params.mode });
  if (params.setupId) query.set("setup_id", params.setupId);
  if (params.asOf) query.set("as_of", params.asOf);
  return request<ResearchBrief>(`/api/analysis/${params.symbol}/brief?${query}`, { method: "POST" });
}

export function getResearchBrief(symbol: string, briefId: string): Promise<ResearchBrief> {
  return request<ResearchBrief>(`/api/analysis/${symbol}/brief/${briefId}`);
}

/** Hardening pass (§19): the Reports page's list -- every saved brief this
 * process has ever generated, never regenerated from current market state. */
export function listRecentBriefs(limit = 100): Promise<BriefListItem[]> {
  return request<BriefListItem[]>(`/api/analysis/briefs?limit=${limit}`);
}

export function getSavedEvidencePacket(symbol: string, packetId: string): Promise<EvidencePacket> {
  return request<EvidencePacket>(`/api/analysis/${symbol}/evidence/${packetId}`);
}

// ---- Forward Prediction Benchmark & Validation Lab (Phase 12) -------------
//
// `postForecast` never accepts a market_as_of -- the same structural
// no-backfill guarantee app.forecasting.service.create_forecast documents
// on the backend: a prospective forecast made through this client can only
// ever be bound to "right now."

export interface CreateForecastParams {
  symbol: string;
  timeframe: Timeframe;
  forecastCategory: ForecastCategoryKind;
  horizonBars: number;
  setupId?: string;
  origin?: ForecastOriginKind;
}

export function postForecast(params: CreateForecastParams): Promise<ForwardForecast> {
  return request<ForwardForecast>(`/api/forecasts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: params.symbol,
      timeframe: params.timeframe,
      forecast_category: params.forecastCategory,
      horizon_bars: params.horizonBars,
      setup_id: params.setupId ?? null,
      origin: params.origin ?? "deterministic_research",
    }),
  });
}

export function listForecasts(params: { symbol?: string; timeframe?: string; status?: string; limit?: number } = {}): Promise<ForwardForecast[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 200));
  return request<ForwardForecast[]>(`/api/forecasts?${query}`);
}

export function getForecast(forecastId: string): Promise<ForwardForecast> {
  return request<ForwardForecast>(`/api/forecasts/${forecastId}`);
}

export function resolveForecast(forecastId: string): Promise<ForecastOutcome> {
  return request<ForecastOutcome>(`/api/forecasts/${forecastId}/resolve`, { method: "POST" });
}

export function getForecastPerformance(symbol?: string): Promise<ForecastPerformanceResponse> {
  const query = new URLSearchParams();
  if (symbol) query.set("symbol", symbol);
  return request<ForecastPerformanceResponse>(`/api/forecasts/performance?${query}`);
}

export function getForecastGate(): Promise<ForwardValidationGateEvaluation> {
  return request<ForwardValidationGateEvaluation>(`/api/forecasts/gate`);
}
