"""Deterministic configuration hashing (#7, #30). A historical research
result is meaningless if we can't reproduce which rules produced it -- this
hashes every threshold that could change what a replay run detects/qualifies,
so two runs with the same hash are guaranteed to have used identical rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.features.config import FeatureConfig
from app.market_structure.config import MarketStructureConfig
from app.research.config import ResearchConfig
from app.setup_detection.config import SetupDetectionConfig
from app.support_resistance.config import SupportResistanceConfig


def build_config_snapshot(
    feature_config: FeatureConfig,
    structure_config: MarketStructureConfig,
    levels_config: SupportResistanceConfig,
    setup_config: SetupDetectionConfig,
    research_config: ResearchConfig,
) -> dict:
    """A plain, JSON-serializable snapshot of every config object that
    influences detection/qualification/research -- stored verbatim on the
    ResearchRun record (#7) so a run's rules are always inspectable, not
    just its hash."""
    return {
        "features": asdict(feature_config),
        "market_structure": asdict(structure_config),
        "support_resistance": asdict(levels_config),
        "setup_detection": asdict(setup_config),
        "research": asdict(research_config),
    }


def compute_config_hash(config_snapshot: dict) -> str:
    canonical = json.dumps(config_snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
