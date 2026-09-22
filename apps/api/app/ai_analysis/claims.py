"""Phase 11 (#B): deterministic EvidenceClaims derived purely from an
already-built EvidencePacket -- no LLM involved. This is the layer an AI
provider's prose must stay grounded to: every claim below is reproducible
from packet fields alone, carries explicit `evidence_refs` (the citation
vocabulary section N's UI expands), and is never itself a buy/sell call.

Claims are appended in a fixed, deterministic order (structure, setup
qualification, historical research, contradictions, catalyst, analogs) so
`derive_evidence_claims` is itself as_of-safe: the same EvidencePacket always
produces the same claim list, in the same order, with the same `claim_id`s.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.ai_analysis.schemas import EvidencePacket
from app.research_intelligence.schemas import ConclusionLabel, ContradictionStatus, EvidenceMaturity

_SMALL_NUMBER_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]

_TIMEFRAME_PHRASES = {
    "1m": "the 1-minute timeframe",
    "5m": "the 5-minute timeframe",
    "15m": "the 15-minute timeframe",
    "1h": "the hourly timeframe",
    "4h": "the 4-hour timeframe",
    "1d": "the daily timeframe",
}


def _spell_count(count: int) -> str:
    if 0 <= count < len(_SMALL_NUMBER_WORDS):
        return _SMALL_NUMBER_WORDS[count]
    return str(count)


def _timeframe_phrase(timeframe) -> str:
    key = timeframe.value if hasattr(timeframe, "value") else str(timeframe)
    return _TIMEFRAME_PHRASES.get(key, f"the {key} timeframe")


def _count_sentence(count: int, noun_singular: str, noun_plural: str, timeframe) -> str:
    """Grammatically correct, deterministic count sentence -- e.g. 'Ten
    breaks of structure were observed on the daily timeframe.' Replaces the
    earlier '{n} break(s) of structure observed on {tf.value}' template,
    which read as unfinished/ungrammatical prose regardless of count."""
    noun = noun_singular if count == 1 else noun_plural
    verb = "was" if count == 1 else "were"
    spelled = _spell_count(count)
    return f"{spelled.capitalize()} {noun} {verb} observed on {_timeframe_phrase(timeframe)}."


class ClaimDirection(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class ClaimStrength(str, Enum):
    """A categorical label, never a fabricated confidence float -- derived
    only from fields the deterministic engines already computed (sample size
    label, evidence maturity, walk-forward/temporal stability), same
    "discrete tiers, not invented numbers" convention as
    app.news.schemas.ClassificationBasis."""

    INSUFFICIENT = "insufficient"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    NOT_APPLICABLE = "not_applicable"


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str
    claim_type: str
    statement: str
    evidence_refs: list[str]
    direction: ClaimDirection
    strength: ClaimStrength
    source: str = "deterministic"
    limitations: list[str] = []


def _claim_id(packet_id: str, claim_type: str, ordinal: int) -> str:
    digest_source = f"{packet_id}|{claim_type}|{ordinal}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:24]


def _maturity_strength(maturity: str) -> ClaimStrength:
    mapping = {
        EvidenceMaturity.INSUFFICIENT.value: ClaimStrength.INSUFFICIENT,
        EvidenceMaturity.PRELIMINARY.value: ClaimStrength.WEAK,
        EvidenceMaturity.MIXED.value: ClaimStrength.MODERATE,
        EvidenceMaturity.REPLICATED.value: ClaimStrength.STRONG,
    }
    return mapping.get(maturity, ClaimStrength.INSUFFICIENT)


def derive_evidence_claims(packet: EvidencePacket) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    counters: dict[str, int] = {}

    def add(claim_type: str, statement: str, refs: list[str], direction: ClaimDirection,
             strength: ClaimStrength, limitations: Optional[list[str]] = None) -> None:
        ordinal = counters.get(claim_type, 0)
        counters[claim_type] = ordinal + 1
        claims.append(
            EvidenceClaim(
                claim_id=_claim_id(packet.packet_id, claim_type, ordinal),
                claim_type=claim_type,
                statement=statement,
                evidence_refs=refs,
                direction=direction,
                strength=strength,
                limitations=limitations or [],
            )
        )

    # ---- Structure / support-resistance -----------------------------------
    sr = packet.support_resistance
    if packet.current_price is not None and sr.nearest_resistance is not None:
        add(
            "price_vs_resistance",
            f"Price ({packet.current_price:g}) is below the nearest resistance zone at "
            f"{sr.nearest_resistance.representative_price:g}.",
            [f"zone:{sr.nearest_resistance.id}"],
            ClaimDirection.NEUTRAL,
            ClaimStrength.NOT_APPLICABLE,
        )
    if packet.current_price is not None and sr.nearest_support is not None:
        add(
            "price_vs_support",
            f"Price ({packet.current_price:g}) is above the nearest support zone at "
            f"{sr.nearest_support.representative_price:g}.",
            [f"zone:{sr.nearest_support.id}"],
            ClaimDirection.NEUTRAL,
            ClaimStrength.NOT_APPLICABLE,
        )

    structure = packet.structure
    if structure.breaks_of_structure:
        add(
            "break_of_structure",
            _count_sentence(
                len(structure.breaks_of_structure), "break of structure", "breaks of structure",
                structure.timeframe,
            ),
            ["structure:breaks_of_structure"],
            ClaimDirection.SUPPORTING,
            ClaimStrength.NOT_APPLICABLE,
        )
    if structure.changes_of_character:
        add(
            "change_of_character",
            _count_sentence(
                len(structure.changes_of_character), "change of character", "changes of character",
                structure.timeframe,
            ),
            ["structure:changes_of_character"],
            ClaimDirection.CONTRADICTING,
            ClaimStrength.NOT_APPLICABLE,
            limitations=["A change of character does not itself confirm a new trend."],
        )

    # ---- Setup qualification/rejection ------------------------------------
    if packet.setup is not None:
        for reason in packet.setup.qualification_reasons:
            add(
                "qualification_reason",
                f"Qualification check passed: {reason}",
                [f"setup:{packet.setup.candidate.id}"],
                ClaimDirection.SUPPORTING,
                ClaimStrength.NOT_APPLICABLE,
            )
        for reason in packet.setup.rejection_reasons:
            add(
                "rejection_reason",
                f"Qualification check failed: {reason}",
                [f"setup:{packet.setup.candidate.id}"],
                ClaimDirection.CONTRADICTING,
                ClaimStrength.NOT_APPLICABLE,
            )
        for reason in packet.setup.conflict_reasons:
            add(
                "conflict",
                f"Conflicting condition present: {reason}",
                [f"setup:{packet.setup.candidate.id}"],
                ClaimDirection.CONTRADICTING,
                ClaimStrength.NOT_APPLICABLE,
            )

    # ---- Historical research ------------------------------------------------
    research = packet.historical_research
    if research is not None:
        run_ref = f"research:{','.join(packet.provenance.research_run_ids)}"
        maturity_strength = _maturity_strength(research.independence.evidence_maturity)
        add(
            "evidence_maturity",
            research.independence.evidence_maturity_basis,
            [run_ref],
            ClaimDirection.NEUTRAL,
            maturity_strength,
        )

        stability = research.independence.conclusion_stability
        if stability is not None:
            if stability.label == ConclusionLabel.SURVIVES:
                direction = ClaimDirection.SUPPORTING
            elif stability.label in (ConclusionLabel.REVERSES, ConclusionLabel.DISAPPEARS):
                direction = ClaimDirection.CONTRADICTING
            elif stability.label == ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE:
                direction = ClaimDirection.UNKNOWN
            else:
                direction = ClaimDirection.NEUTRAL
            add(
                "qualified_vs_rejected_stability",
                f"Qualified-vs-rejected comparison: {stability.label.value.replace('_', ' ')} "
                f"({stability.label_basis}).",
                [run_ref],
                direction,
                maturity_strength,
            )

        for warning in research.concentration.warnings:
            add(
                "concentration_warning",
                warning.warning,
                [run_ref],
                ClaimDirection.UNKNOWN,
                ClaimStrength.WEAK,
                limitations=["Concentrated evidence is less generalizable than dispersed evidence."],
            )

        if research.overlap.overlap_fraction > 0:
            add(
                "overlap",
                f"{research.overlap.overlap_fraction:.0%} of the sample's forward-return windows "
                "overlap in time, so raw sample count overstates independent evidence.",
                [run_ref],
                ClaimDirection.UNKNOWN,
                ClaimStrength.WEAK,
            )

        for contradiction in research.contradictions:
            if contradiction.status == ContradictionStatus.NOT_SUPPORTED:
                direction = ClaimDirection.CONTRADICTING
            elif contradiction.status == ContradictionStatus.INSUFFICIENT_DATA:
                direction = ClaimDirection.UNKNOWN
            else:
                direction = ClaimDirection.SUPPORTING
            add(
                "contradiction_check",
                contradiction.description,
                [run_ref],
                direction,
                maturity_strength,
            )

    # ---- Catalyst context ---------------------------------------------------
    catalyst = packet.catalyst_context
    if catalyst is not None:
        label = catalyst.label.value
        if "supported" in label or "persisted" in label:
            direction = ClaimDirection.SUPPORTING
        elif "conflicted" in label:
            direction = ClaimDirection.CONTRADICTING
        elif "faded" in label:
            direction = ClaimDirection.NEUTRAL
        else:
            direction = ClaimDirection.UNKNOWN
        refs = ["catalyst:none"] if catalyst.nearest_catalyst is None else [
            f"catalyst:{catalyst.nearest_catalyst.event_id}"
        ]
        add(
            "catalyst_context",
            catalyst.label_basis,
            refs,
            direction,
            ClaimStrength.NOT_APPLICABLE,
        )

    # ---- Historical analogs ---------------------------------------------------
    analogs = packet.historical_analogs
    if analogs is not None and analogs.analogs:
        add(
            "analog_summary",
            f"{len(analogs.analogs)} historical analog(s) found, spanning "
            f"{analogs.diversity.distinct_episode_count} distinct episode(s) and "
            f"{analogs.diversity.distinct_symbol_count} symbol(s).",
            [f"analog:{a.setup_id}" for a in analogs.analogs],
            ClaimDirection.NEUTRAL,
            ClaimStrength.NOT_APPLICABLE,
            limitations=(
                ["Similarity is computed only from detection-time information; "
                 "outcomes never influence which analogs were selected."]
            ),
        )

    return claims
