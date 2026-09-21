"""Phase 12.1: Automatic Live Data & Event-Driven Updates.

This package is a thin, honest scheduling/fan-out layer over the existing
MarketDataProvider/EvidencePacket/forecasting machinery -- it never
duplicates a statistic, never invents a data point, and never labels
polled data as "real-time" unless the active provider's own
ProviderCapabilities says so. See docs/decisions/0017-automatic-live-data
.md for the full architecture rationale.
"""
