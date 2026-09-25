"""Phase 14: Alerts, continuous monitoring, and the cross-symbol Decision
Scanner. An AlertEvent is created only from a deterministic change already
produced by the (unmodified) Decision Engine -- this package never invents
new evidence, never scores, never recommends BUY/SELL. See schemas.py for
the full model and service.py for the only place an AlertEvent is created.
"""
