"""Individual setup detectors. Each module exposes `detect(inputs) ->
list[SetupCandidate]` and owns exactly one deterministic definition -- see
docs/decisions/0007 for why fundamentally different behaviors (e.g. a
wick-only failed breakout vs. a confirmed-then-reversed one) are never
combined into a single vague detector."""
