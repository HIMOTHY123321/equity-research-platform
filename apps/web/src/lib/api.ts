import type {
  AnalogQueryResponse,
  CandlesResponse,
  FeatureSnapshot,
  LedgerEntriesResponse,
  MarketStructureSnapshot,
  ResearchQueryResponse,
  ResearchRun,
  ResearchRunSummary,
  ResearchSnapshot,
  SetupCandidate,
  SetupDetectionSnapshot,
  SnapshotComparison,
  SupportResistanceSnapshot,
  Timeframe,
  UniverseReplayResponse,
  WatchlistSymbol,
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
): Promise<AnalogQueryResponse> {
  return request<AnalogQueryResponse>(`/api/research/analogs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query_candidate: queryCandidate,
      corpus_run_ids: corpusRunIds,
      top_n: topN ?? null,
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
