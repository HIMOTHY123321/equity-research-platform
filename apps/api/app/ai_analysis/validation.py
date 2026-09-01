"""Phase 11 (#D/#O): grounds every AI-produced ResearchBrief against the
EvidenceClaims it was given. Nothing here trusts provider output -- external
AI responses (and, transitively, any text an untrusted news headline or
source field could have injected into a prompt, #O) are validated the same
way regardless of which provider produced them.

Three independent checks, each a plain deterministic function so they are
individually unit-testable:

1. Evidence-ref grounding -- every ref the brief cites must already exist on
   one of the supplied claims. A citation to a nonexistent id is rejected.
2. Numeric grounding -- every number appearing in the brief's prose must be
   traceable (within rounding tolerance) to a number already present
   somewhere in the EvidencePacket/claims. A number that isn't is treated as
   invented (a price, a sample count, a percentage the AI made up).
3. Banned language -- BUY/SELL/recommendation directives and probability/
   certainty claims ("73% chance", "guaranteed") are never allowed,
   regardless of grounding, per Phase 9's RANKING GATE and the product's
   "descriptive, never predictive" boundary.

A brief that fails any check is rejected outright (never partially patched)
-- app.ai_analysis.brief falls back to a deterministic-only brief built
straight from `claims` when that happens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai_analysis.claims import EvidenceClaim
from app.ai_analysis.research_brief import ResearchBrief
from app.ai_analysis.schemas import EvidencePacket

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
# ISO-8601 timestamps are legitimate prose (e.g. "as of 2026-09-01T12:00:00Z")
# but their digits are not "facts" the numeric-grounding check should try to
# trace back to packet data -- stripped before that check runs.
_ISO_DATETIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
)

# Small connective integers (bar counts, horizon counts, list lengths) that
# are legitimate in prose without being individually grounded -- keeps the
# numeric check from rejecting normal sentences like "over the next 5 bars."
_UNGROUNDED_SAFE_INTEGERS = {float(n) for n in range(0, 11)}

_BANNED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("buy_recommendation", re.compile(r"\b(strong\s+)?buy\b", re.IGNORECASE)),
    ("sell_recommendation", re.compile(r"\b(strong\s+)?sell\b", re.IGNORECASE)),
    ("recommendation_language", re.compile(r"\brecommend(?:ed|s|ation)?\b", re.IGNORECASE)),
    ("probability_claim", re.compile(r"\d+(?:\.\d+)?\s*%\s*chance", re.IGNORECASE)),
    ("probability_claim_alt", re.compile(r"\bprobability\s+of\b", re.IGNORECASE)),
    ("certainty_claim", re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE)),
    ("certainty_claim_alt", re.compile(r"\bsure\s+thing\b", re.IGNORECASE)),
]

_TEXT_FIELDS = (
    "situation_summary",
    "setup_explanation",
    "catalyst_context",
    "historical_context",
)
_TEXT_LIST_FIELDS = (
    "supporting_evidence",
    "contradictory_evidence",
    "uncertainty",
    "invalidation_conditions",
    "monitor_next",
)


@dataclass
class GroundingViolation:
    code: str
    detail: str


@dataclass
class GroundingResult:
    is_valid: bool
    violations: list[GroundingViolation] = field(default_factory=list)


def _all_text(brief: ResearchBrief) -> list[str]:
    texts = [getattr(brief, f) for f in _TEXT_FIELDS]
    for f in _TEXT_LIST_FIELDS:
        texts.extend(getattr(brief, f))
    return [t for t in texts if t]


def _valid_evidence_refs(claims: list[EvidenceClaim]) -> set[str]:
    refs: set[str] = set()
    for claim in claims:
        refs.update(claim.evidence_refs)
    return refs


def _packet_numbers(packet: EvidencePacket) -> set[float]:
    numbers: set[float] = set()

    def add(value) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numbers.add(round(float(value), 1))

    def add_text(text: str) -> None:
        stripped = _ISO_DATETIME_PATTERN.sub(" ", text)
        for match in _NUMBER_PATTERN.finditer(stripped):
            numbers.add(round(float(match.group()), 1))

    add(packet.current_price)

    if packet.setup is not None:
        for criterion in packet.setup.candidate.invalidation_criteria:
            add_text(criterion)

    sr = packet.support_resistance
    for zone in (sr.nearest_support, sr.nearest_resistance):
        if zone is not None:
            add(zone.representative_price)
            add(zone.lower_bound)
            add(zone.upper_bound)

    add(packet.features.atr.value if packet.features.atr is not None else None)
    add(
        packet.features.intraday_relative_volume.intraday_relative_volume
        if packet.features.intraday_relative_volume is not None
        else None
    )
    add(packet.features.gap.gap_percent if packet.features.gap is not None else None)

    research = packet.historical_research
    if research is not None:
        add(research.sample_count)
        add(research.catalyst_filtered_raw_sample_count)
        add(research.unfiltered_raw_sample_count)
        add(research.independence.sample_composition.raw_count)
        add(research.independence.sample_composition.episode_count)
        for count in research.independence.sample_composition.purged_counts_by_horizon.values():
            add(count)
        add(research.overlap.overlap_fraction * 100)
        for warning in research.concentration.warnings:
            add(warning.share * 100)

    catalyst = packet.catalyst_context
    if catalyst is not None and catalyst.nearest_catalyst is not None:
        add(catalyst.nearest_catalyst.source_count)
        add(catalyst.nearest_catalyst.hours_before_setup)
        add(catalyst.nearest_catalyst.hours_after_setup)

    analogs = packet.historical_analogs
    if analogs is not None:
        add(len(analogs.analogs))
        add(analogs.diversity.distinct_episode_count)
        add(analogs.diversity.distinct_symbol_count)

    return numbers


def check_evidence_refs(brief: ResearchBrief, claims: list[EvidenceClaim]) -> list[GroundingViolation]:
    valid_refs = _valid_evidence_refs(claims)
    violations = []
    for ref in brief.evidence_refs:
        if ref not in valid_refs:
            violations.append(GroundingViolation("unknown_evidence_ref", f"Cited ref {ref!r} does not exist"))
    return violations


def _claim_statement_numbers(claims: list[EvidenceClaim]) -> set[float]:
    """Claim statements are themselves deterministic text (never AI-authored,
    see app.ai_analysis.claims) -- any number already spelled out in one is
    already-grounded evidence, not something the AI invented. Extracting
    with the same regex used against brief text also sidesteps float-
    formatting mismatches (e.g. `:g` vs a fixed rounding) entirely, since
    both sides are parsed identically."""
    numbers: set[float] = set()
    for claim in claims:
        stripped = _ISO_DATETIME_PATTERN.sub(" ", claim.statement)
        for match in _NUMBER_PATTERN.finditer(stripped):
            numbers.add(round(float(match.group()), 1))
    return numbers


def check_numeric_grounding(
    brief: ResearchBrief, packet: EvidencePacket, claims: list[EvidenceClaim]
) -> list[GroundingViolation]:
    allowed = _packet_numbers(packet) | _claim_statement_numbers(claims) | _UNGROUNDED_SAFE_INTEGERS
    violations = []
    for text in _all_text(brief):
        stripped = _ISO_DATETIME_PATTERN.sub(" ", text)
        for match in _NUMBER_PATTERN.finditer(stripped):
            value = round(float(match.group()), 1)
            if value not in allowed:
                violations.append(
                    GroundingViolation(
                        "unsupported_number", f"Number {match.group()!r} in {text!r} is not grounded"
                    )
                )
    return violations


def check_banned_language(brief: ResearchBrief) -> list[GroundingViolation]:
    violations = []
    for text in _all_text(brief):
        for code, pattern in _BANNED_PATTERNS:
            if pattern.search(text):
                violations.append(GroundingViolation(code, f"Banned language matched in {text!r}"))
    return violations


def validate_research_brief(
    brief: ResearchBrief, packet: EvidencePacket, claims: list[EvidenceClaim]
) -> GroundingResult:
    violations = (
        check_evidence_refs(brief, claims)
        + check_numeric_grounding(brief, packet, claims)
        + check_banned_language(brief)
    )
    return GroundingResult(is_valid=not violations, violations=violations)
