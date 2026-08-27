"""Phase 7: historical replay, setup ledger, and outcome research.

Strict domain split (see docs/decisions/0008): detection-time information
(what `app.setup_detection` computed at timestamp T) is immutable and never
touches future candles. Evaluation-time information (what price did
afterward) is computed here, always from candles strictly after T, and is
kept in a completely separate schema (`SetupOutcome`) so the boundary is
structurally impossible to blur."""
