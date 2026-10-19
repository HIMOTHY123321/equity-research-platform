import type {
  AlertEvent,
  AlertPreference,
  AnalogQueryResponse,
  AnalysisMode,
  BriefListItem,
  CandlesResponse,
  CatalystEvent,
  CatalystEventDetail,
  CatalystResearchQueryResponse,
  CohortStatistics,
  DecisionEvidencePacket,
  DecisionExplanations,
  DecisionPlan,
  DecisionTransition,
  EvidenceDiffSnapshot,
  EvidencePacket,
  FeatureSnapshot,
  ForecastCategoryKind,
  ForecastOriginKind,
  ForecastOutcome,
  ForecastPerformanceResponse,
  ForwardForecast,
  ForwardValidationGateEvaluation,
  HistoricalProspectiveComparison,
  LedgerEntriesResponse,
  LiveStatusResponse,
  MarketReaction,
  MarketStructureSnapshot,
  MonitoringSubscription,
  NormalizedNewsArticle,
  ObservationStatus,
  OpportunityListResponse,
  PushPreference,
  PushStatus,
  ResearchBrief,
  ResearchQueryResponse,
  ResearchRun,
  ResearchRunSummary,
  ResearchSnapshot,
  ProspectiveObservation,
  ScannerRow,
  SetupCandidate,
  SetupCatalystContext,
  SetupDetectionSnapshot,
  SignalGateEvaluation,
  SignalGateHistoryEntry,
  SnapshotComparison,
  StockThesis,
  SupportResistanceSnapshot,
  SymbolMatch,
  SymbolSearchResponse,
  Timeframe,
  UniverseReplayResponse,
  ValidationSummary,
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

/** Phase 16.1 (§2): the session lives ONLY in the HttpOnly `amd_session`
 * cookie -- this client never reads, stores, or attaches a token itself.
 * `credentials: "include"` is what makes the browser send that cookie
 * (and accept a new one via Set-Cookie) on every request, including
 * cross-port localhost dev (frontend :3000, backend :8000 -- same-site,
 * cross-origin, which still carries a SameSite=Lax cookie). */
const AUTH_ROUTES_EXEMPT_FROM_REDIRECT = new Set(["/api/auth/login", "/api/auth/signup", "/api/auth/me"]);

async function handleResponse<T>(res: Response, path: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message = body?.detail ?? `Request failed (${res.status})`;
    if (res.status === 401 && typeof window !== "undefined" && !AUTH_ROUTES_EXEMPT_FROM_REDIRECT.has(path)) {
      window.dispatchEvent(new CustomEvent("amd:session-expired"));
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Phase 19.4: every browser-side call goes through the same-origin
 * `/api/backend/*` proxy (src/app/api/backend/[...path]/route.ts), never
 * straight to the backend -- the deployed backend's `amd_session` cookie
 * is host-only to its own onrender.com domain, so a direct cross-origin
 * call from the browser can never carry it. The proxy reads the
 * FRONTEND's own cookie server-side and forwards it as a Bearer token.
 *
 * Server Components (e.g. app/page.tsx's `checkApiHealth()` during SSR)
 * call the backend directly instead: that fetch runs on this Node
 * process, never in a browser, so there is no CORS/cross-site-cookie
 * question to begin with, and no relative URL to resolve against either
 * (unlike a browser, Next's server-side `fetch` cannot resolve a
 * relative path against "this app's own origin" at all). */
function requestUrl(path: string): string {
  return typeof window === "undefined" ? `${getApiBaseUrl()}${path}` : `/api/backend${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(requestUrl(path), { cache: "no-store", credentials: "include", ...init });
  return handleResponse<T>(res, path);
}

/** Phase 19.3: login/signup/logout/me must go through this app's OWN
 * same-origin Next.js routes (src/app/api/auth/*\/route.ts), never
 * straight to the backend -- the deployed backend's `amd_session` cookie
 * is host-only to its own onrender.com domain and can never reach the
 * frontend's different onrender.com domain, so the frontend mints its
 * own cookie via these routes instead. See src/lib/auth-proxy.ts for the
 * full explanation. */
async function requestSameOrigin<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", credentials: "include", ...init });
  return handleResponse<T>(res, path);
}

export async function checkApiHealth(): Promise<HealthStatus | null> {
  try {
    return await request<HealthStatus>("/health");
  } catch {
    return null;
  }
}

// ---- Auth (Phase 16.1) -----------------------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  status: string;
  role: string;
  plan: string;
  timezone: string;
  created_at: string;
}

export function signup(email: string, password: string): Promise<AuthUser> {
  return requestSameOrigin<{ user: AuthUser }>("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then((res) => res.user);
}

export function login(email: string, password: string): Promise<AuthUser> {
  return requestSameOrigin<{ user: AuthUser }>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then((res) => res.user);
}

export function logout(): Promise<void> {
  return requestSameOrigin<void>("/api/auth/logout", { method: "POST" });
}

/** Resolves to `null` (never throws) when there is no valid session --
 * callers use this to determine signed-in state, not just to fetch a
 * profile. */
export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    return await requestSameOrigin<AuthUser>("/api/auth/me");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

export interface PlanOut {
  plan: string;
  entitlements: string[];
}

export function getMyPlan(): Promise<PlanOut> {
  return request<PlanOut>("/api/billing/plan");
}

export interface SystemStatus {
  environment: string;
  worker_mode: string;
  market_data: { provider: string; is_licensed_commercial_feed: boolean; development_only_fallback_in_use: boolean };
  news: { provider: string; development_only_fallback_in_use: boolean };
  ai_analysis: { provider: string };
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/api/system/status");
}

/** `before`, when given (lazy pan-left pagination), requests the `limit`
 * candles immediately preceding that instant instead of the most recent
 * `limit` -- an older-history page, never a fresh/initial load. */
export function getCandles(
  symbol: string,
  timeframe: Timeframe,
  limit = 200,
  before?: string,
): Promise<CandlesResponse> {
  const params = new URLSearchParams({ timeframe, limit: String(limit) });
  if (before) params.set("before", before);
  return request<CandlesResponse>(`/api/market/${symbol}/candles?${params}`);
}

/** §5: the one source of truth for whether market data is genuinely
 * streaming vs. polled -- never inferred from freshness/age alone. */
export function getLiveStatus(): Promise<LiveStatusResponse> {
  return request<LiveStatusResponse>("/api/live/status");
}

/** Phase 19.6: issues a short-lived (tens of seconds), single-use WS
 * ticket -- the only thing `liveClient.ts` is allowed to put on the
 * WebSocket URL. Goes through the same `request()` helper (and so the
 * same `/api/backend/*` same-origin proxy in the browser) as every other
 * authenticated REST call -- never a new/dedicated proxy route, and the
 * real session JWT never appears in this response. */
export interface WsTicket {
  ticket: string;
  expires_in: number;
}

export function getLiveStreamTicket(): Promise<WsTicket> {
  return request<WsTicket>("/api/live/ws-ticket", { method: "POST" });
}

// ---- Dev-only live simulator (Phase 17 §60/§79/§99) ------------------------
// Every one of these 404s unless the backend has ENABLE_DEV_LIVE_SIMULATOR
// set (impossible in production -- see app.api.routes.dev_live). Only
// called from src/app/dev/live-simulator, which itself refuses to render
// outside a development build (see that page's own guard).

export interface DevSimulatorStatus {
  enabled: boolean;
  connected: boolean;
  connect_count: number;
  subscriptions: Record<string, string[]>;
}

export function getDevSimulatorStatus(): Promise<DevSimulatorStatus> {
  return request<DevSimulatorStatus>("/api/dev/live-simulator/status");
}

export function pushDevSimulatorTrade(symbol: string, price: number): Promise<{ pushed: boolean }> {
  return request<{ pushed: boolean }>("/api/dev/live-simulator/trade", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, price }),
  });
}

export function pushDevSimulatorDisconnect(): Promise<{ pushed: boolean }> {
  return request<{ pushed: boolean }>("/api/dev/live-simulator/disconnect", { method: "POST" });
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

// ---- Trader Decision Engine (Phase 13) ------------------------------------
//
// `scanDecisions` always evaluates "right now" -- same no-backfill shape as
// postForecast above -- and is the only way a new DecisionPlan is created
// from this client; every other call here only ever reads already-
// persisted, already-decided state.

export function scanDecisions(symbol: string, timeframe: Timeframe): Promise<DecisionPlan[]> {
  const query = new URLSearchParams({ timeframe });
  return request<DecisionPlan[]>(`/api/decisions/${symbol}/scan?${query}`, { method: "POST" });
}

export function listDecisions(
  params: { symbol?: string; timeframe?: string; state?: string; openOnly?: boolean; limit?: number } = {}
): Promise<DecisionPlan[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.state) query.set("state", params.state);
  if (params.openOnly) query.set("open_only", "true");
  query.set("limit", String(params.limit ?? 200));
  return request<DecisionPlan[]>(`/api/decisions?${query}`);
}

export function getDecision(decisionPlanId: string): Promise<DecisionPlan> {
  return request<DecisionPlan>(`/api/decisions/${decisionPlanId}`);
}

export function getDecisionTransitions(decisionPlanId: string): Promise<DecisionTransition[]> {
  return request<DecisionTransition[]>(`/api/decisions/${decisionPlanId}/transitions`);
}

export function getDecisionEvidence(decisionPlanId: string): Promise<DecisionEvidencePacket> {
  return request<DecisionEvidencePacket>(`/api/decisions/${decisionPlanId}/evidence`);
}

export function getDecisionExplanations(decisionPlanId: string): Promise<DecisionExplanations> {
  return request<DecisionExplanations>(`/api/decisions/${decisionPlanId}/explanations`);
}

/** Phase 18 (§11): the deterministic "WHAT CHANGED" record, oldest first. */
export function getDecisionEvidenceDiffs(decisionPlanId: string): Promise<EvidenceDiffSnapshot[]> {
  return request<EvidenceDiffSnapshot[]>(`/api/decisions/${decisionPlanId}/evidence-diffs`);
}

export function getForecastGate(): Promise<ForwardValidationGateEvaluation> {
  return request<ForwardValidationGateEvaluation>(`/api/forecasts/gate`);
}

// ---- Alerts, Monitoring & Decision Scanner (Phase 14) ---------------------

export function listAlerts(
  params: {
    symbol?: string;
    alertType?: string;
    severity?: string;
    origin?: string;
    unreadOnly?: boolean;
    limit?: number;
  } = {},
): Promise<AlertEvent[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.alertType) query.set("alert_type", params.alertType);
  if (params.severity) query.set("severity", params.severity);
  if (params.origin) query.set("origin", params.origin);
  if (params.unreadOnly) query.set("unread_only", "true");
  query.set("limit", String(params.limit ?? 200));
  return request<AlertEvent[]>(`/api/alerts?${query}`);
}

export function getUnreadAlertCount(symbol?: string): Promise<{ count: number }> {
  const query = new URLSearchParams();
  if (symbol) query.set("symbol", symbol);
  return request<{ count: number }>(`/api/alerts/unread-count?${query}`);
}

export function acknowledgeAlert(alertId: string): Promise<void> {
  return request<void>(`/api/alerts/${alertId}/acknowledge`, { method: "POST" });
}

export function acknowledgeAllAlerts(symbol?: string): Promise<{ acknowledged: number }> {
  const query = new URLSearchParams();
  if (symbol) query.set("symbol", symbol);
  return request<{ acknowledged: number }>(`/api/alerts/acknowledge-all?${query}`, { method: "POST" });
}

export function getAlertPreferences(): Promise<AlertPreference[]> {
  return request<AlertPreference[]>(`/api/alerts/preferences`);
}

export function setAlertPreference(alertType: string, enabled: boolean): Promise<AlertPreference> {
  return request<AlertPreference>(`/api/alerts/preferences/${alertType}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

/** Phase 20: this user's own phone-push on/off switch. Defaults to
 * disabled -- see PushPreference's own doc comment. */
export function getPushPreference(): Promise<PushPreference> {
  return request<PushPreference>(`/api/alerts/push-preference`);
}

export function setPushPreference(enabled: boolean): Promise<PushPreference> {
  return request<PushPreference>(`/api/alerts/push-preference`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

/** Whether the server has Pushover configured at all -- unauthenticated
 * (same global-system-fact shape as getSystemStatus), never returns a
 * credential value. */
export function getPushStatus(): Promise<PushStatus> {
  return request<PushStatus>(`/api/alerts/push-status`);
}

/** Phase 20.1: submits THIS user's OWN Pushover User Key over the same
 * authenticated HTTPS session every other write uses. The key is never
 * returned by any response, including this one -- only `key_configured`
 * is. */
export function setPushKey(pushoverUserKey: string): Promise<{ key_configured: boolean }> {
  return request<{ key_configured: boolean }>(`/api/alerts/push-key`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pushover_user_key: pushoverUserKey }),
  });
}

export function deletePushKey(): Promise<{ key_configured: boolean }> {
  return request<{ key_configured: boolean }>(`/api/alerts/push-key`, { method: "DELETE" });
}

export function listMonitoring(): Promise<MonitoringSubscription[]> {
  return request<MonitoringSubscription[]>(`/api/monitoring`);
}

export function enableMonitoring(symbol: string): Promise<MonitoringSubscription> {
  return request<MonitoringSubscription>(`/api/monitoring/${symbol}`, { method: "POST" });
}

export function disableMonitoring(symbol: string): Promise<void> {
  return request<void>(`/api/monitoring/${symbol}`, { method: "DELETE" });
}

export function getDecisionScanner(): Promise<ScannerRow[]> {
  return request<ScannerRow[]>(`/api/decisions/scanner`);
}

// Phase 15: Prospective Validation & Signal Qualification. Research only
// -- no route in this group ever returns a BUY/SELL, probability, or
// confidence-score field.

export function getValidationStatus(): Promise<ObservationStatus> {
  return request<ObservationStatus>(`/api/validation/status`);
}

export function getSignalGate(timeframe: Timeframe = "1h"): Promise<SignalGateEvaluation> {
  return request<SignalGateEvaluation>(`/api/validation/gate?timeframe=${timeframe}`);
}

export function getSignalGateHistory(limit = 50): Promise<SignalGateHistoryEntry[]> {
  return request<SignalGateHistoryEntry[]>(`/api/validation/gate/history?limit=${limit}`);
}

export function getProspectiveObservations(params: {
  symbol?: string;
  setupType?: string;
  direction?: string;
  timeframe?: string;
  eventType?: string;
  resolvedOnly?: boolean;
} = {}): Promise<ProspectiveObservation[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.setupType) query.set("setup_type", params.setupType);
  if (params.direction) query.set("direction", params.direction);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.eventType) query.set("event_type", params.eventType);
  if (params.resolvedOnly) query.set("resolved_only", "true");
  const qs = query.toString();
  return request<ProspectiveObservation[]>(`/api/validation/observations${qs ? `?${qs}` : ""}`);
}

export function getValidationCohort(params: {
  eventType: string;
  horizonBars?: number;
  timeframe?: Timeframe;
  symbol?: string;
  setupType?: string;
  direction?: string;
}): Promise<CohortStatistics> {
  const query = new URLSearchParams({ event_type: params.eventType });
  if (params.horizonBars) query.set("horizon_bars", String(params.horizonBars));
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.setupType) query.set("setup_type", params.setupType);
  if (params.direction) query.set("direction", params.direction);
  return request<CohortStatistics>(`/api/validation/cohorts?${query.toString()}`);
}

export function getHistoricalComparison(params: {
  symbol: string;
  setupType: string;
  direction: string;
  horizonBars?: number;
}): Promise<HistoricalProspectiveComparison> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    setup_type: params.setupType,
    direction: params.direction,
  });
  if (params.horizonBars) query.set("horizon_bars", String(params.horizonBars));
  return request<HistoricalProspectiveComparison>(`/api/validation/historical-comparison?${query.toString()}`);
}

export function getValidationSummary(params: {
  timeframe?: Timeframe;
  horizonBars?: number;
} = {}): Promise<ValidationSummary> {
  const query = new URLSearchParams();
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.horizonBars) query.set("horizon_bars", String(params.horizonBars));
  const qs = query.toString();
  return request<ValidationSummary>(`/api/validation/summary${qs ? `?${qs}` : ""}`);
}

// Phase 19 (Part 3/Part 2): Stock Thesis + Opportunity Intelligence.

export function getStockThesis(symbol: string, timeframe: Timeframe = "1h", asOf?: string): Promise<StockThesis> {
  const query = new URLSearchParams({ timeframe });
  if (asOf) query.set("as_of", asOf);
  return request<StockThesis>(`/api/symbols/${symbol}/thesis?${query.toString()}`);
}

export function getOpportunities(params: {
  timeframe?: Timeframe;
  category?: string;
  setupType?: string;
  sort?: "state" | "symbol" | "recency";
} = {}): Promise<OpportunityListResponse> {
  const query = new URLSearchParams();
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.category) query.set("category", params.category);
  if (params.setupType) query.set("setup_type", params.setupType);
  if (params.sort) query.set("sort", params.sort);
  const qs = query.toString();
  return request<OpportunityListResponse>(`/api/opportunities${qs ? `?${qs}` : ""}`);
}
