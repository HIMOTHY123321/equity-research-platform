"""Phase 11 (#D/#O): grounds every AI-produced ResearchBrief against the
EvidenceClaims it was given. Nothing here trusts provider output -- external
AI responses (and, transitively, any text an untrusted news headline or
source field could have injected into a prompt, #O) are validated the same
way regardless of which provider produced them.

Checks, each a plain deterministic function so they are individually
unit-testable:

1. Evidence-ref grounding -- every ref the brief cites must already exist on
   one of the supplied claims. A citation to a nonexistent id is rejected.
2. Numeric grounding -- every number appearing in the brief's prose must be
   traceable (within rounding tolerance) to a number already present
   somewhere in the EvidencePacket/claims. A number that isn't is treated as
   invented (a price, a sample count, a percentage the AI made up).
3. Typed factual-claim grounding (#Phase 11.1 I) -- a small set of common,
   *recognizable* statement shapes are checked against the SPECIFIC typed
   field they claim to describe, not just "this number appears somewhere in
   the packet": a price described as a resistance/support level must match
   an actual resistance/support zone (not merely a coincidentally-grounded
   unrelated number); an episode/sample count must match the actual
   independence-adjusted count; a catalyst timing claim must be derivable
   from the actual catalyst timestamps. This is strictly additive to #2 --
   it never widens what's accepted, only narrows it for statement shapes it
   recognizes. Deliberately narrow in scope: subjective prose ("momentum is
   fading") is never typed-checked, only claims with an unambiguous
   quantitative shape.
4. Banned language -- BUY/SELL/recommendation directives and probability/
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
# Timestamps are legitimate prose (e.g. "as of 2026-09-01T12:00:00Z", or the
# exchange-local "2026-09-21 19:52:29 EDT" format `format_exchange_timestamp`
# produces -- #5/#7 hardening) but their digits are not "facts" the
# numeric-grounding check should try to trace back to packet data, so both
# forms are stripped before that check runs. Without the second alternative,
# a correctly-timezone-converted display timestamp reads as several
# ungrounded numbers (hour/minute/second) and gets rejected exactly like an
# AI-invented figure would -- it isn't one, it's the same `as_of`/
# `generated_at` instant already present (and grounded) as an ISO string.
_ISO_DATETIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
    r"|\s\d{2}:\d{2}:\d{2}(?:\s[A-Z]{2,5})?)?"
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
    ("win_rate_claim", re.compile(r"\d+(?:\.\d+)?\s*%\s*win\s*rate", re.IGNORECASE)),
    # (Phase 12 #E) "NN% confident"/"NN% confidence" is a probability claim
    # by another name -- banned the same way "NN% chance" already is. Not a
    # bare ban on the word "confidence" (legitimate elsewhere, e.g. bootstrap
    # confidence intervals): only the percent-prefixed claim form matches.
    ("confidence_claim", re.compile(r"\d+(?:\.\d+)?\s*%\s*confiden", re.IGNORECASE)),
    ("certainty_claim", re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE)),
    ("certainty_claim_alt", re.compile(r"\bsure\s+thing\b", re.IGNORECASE)),
    # (Phase 11.1 #J) Defense in depth: a brief's own text should never
    # contain prompt-injection-style phrasing or a fabricated claim that
    # the RANKING GATE (a static, binding constant -- app.ai_analysis
    # .schemas.RANKING_GATE_STATUS) was ever anything but FAIL. Untrusted
    # provider content is never trusted to begin with (#O); this catches
    # the case where a brief's own prose echoes/acts on an injection
    # attempt rather than reporting it as plain data.
    ("prompt_injection_marker", re.compile(r"ignore\s+all\s+(?:previous\s+)?instructions", re.IGNORECASE)),
    ("prompt_injection_marker_alt", re.compile(r"</?system>", re.IGNORECASE)),
    (
        "ranking_gate_override_claim",
        re.compile(r"ranking\s+gate\s*(?:[:=]|is|has)?\s*(?:passed|pass|ok|success)", re.IGNORECASE),
    ),
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
        for alt in packet.setup.rejected_alternatives:
            add(alt.observed_value)
            add(alt.required_value)
            if alt.failed_requirement:
                add_text(alt.failed_requirement)

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
        add(analogs.diversity.max_same_episode_count)
        if analogs.diversity.dominant_symbol_share is not None:
            add(round(analogs.diversity.dominant_symbol_share * 100))

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


_PRICE_LEVEL_PATTERN = re.compile(
    # A dollar-prefixed amount, or a decimal price (real prices in this
    # product are never bare integers -- "2 zones"/"3 levels" are counts,
    # not prices, and must NOT match here; requiring a `$` or a decimal
    # point is what tells the two apart).
    r"\$(\d+(?:\.\d+)?)\s*(?:resistance|support|zone|level)"
    r"|(\d+\.\d+)\s*(?:resistance|support|zone|level)"
    r"|(?:resistance|support|zone|level)(?:\s+\w+){0,3}?\s+(?:at|of|near)?\s*\$(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_EPISODE_COUNT_PATTERN = re.compile(
    r"(\d+)\s*(?:independent\s+)?episodes?", re.IGNORECASE
)
_RAW_SAMPLE_COUNT_PATTERN = re.compile(
    r"(\d+)\s*(?:raw\s+)?samples?\b", re.IGNORECASE
)
_TIMING_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(before|after)\b", re.IGNORECASE
)

# A price level match is "close enough" if within this fraction of the
# claimed value (formatting/rounding tolerance) -- never a wide enough band
# to let a genuinely different level pass as the same one.
_PRICE_TOLERANCE_FRACTION = 0.005
_TIMING_TOLERANCE_HOURS = 0.5


def _known_zone_prices(packet: EvidencePacket) -> set[float]:
    sr = packet.support_resistance
    prices: set[float] = set()
    for zone in (
        [sr.nearest_support, sr.nearest_resistance]
        + list(sr.active_support_zones)
        + list(sr.active_resistance_zones)
        + list(sr.recent_broken_zones)
    ):
        if zone is not None:
            prices.add(zone.representative_price)
            prices.add(zone.lower_bound)
            prices.add(zone.upper_bound)
    return prices


def _price_is_grounded(value: float, known: set[float]) -> bool:
    if not known:
        return False
    tolerance = max(0.01, value * _PRICE_TOLERANCE_FRACTION)
    return any(abs(value - k) <= tolerance for k in known)


def check_typed_price_level_claims(brief: ResearchBrief, packet: EvidencePacket) -> list[GroundingViolation]:
    """(#Phase 11.1 I) "$214.37 resistance" must match an actual
    support/resistance zone's price -- not merely some unrelated grounded
    number elsewhere in the packet (e.g. a sample count that happens to
    coincide numerically)."""
    known = _known_zone_prices(packet)
    violations = []
    for text in _all_text(brief):
        for match in _PRICE_LEVEL_PATTERN.finditer(text):
            raw = match.group(1) or match.group(2) or match.group(3)
            value = float(raw)
            if not _price_is_grounded(value, known):
                violations.append(
                    GroundingViolation(
                        "unsupported_price_level",
                        f"Price level {raw!r} in {text!r} does not match any support/resistance zone",
                    )
                )
    return violations


def check_typed_episode_claims(brief: ResearchBrief, packet: EvidencePacket) -> list[GroundingViolation]:
    """(#Phase 11.1 I) "14 independent episodes"/"N raw samples" must match
    the packet's own independence-adjusted counts exactly -- not just be
    grounded to *some* number anywhere in the packet."""
    research = packet.historical_research
    violations = []
    episode_count = (
        research.independence.sample_composition.episode_count if research is not None else None
    )
    raw_count = research.independence.sample_composition.raw_count if research is not None else None

    for text in _all_text(brief):
        for match in _EPISODE_COUNT_PATTERN.finditer(text):
            value = int(match.group(1))
            if episode_count is None or value != episode_count:
                violations.append(
                    GroundingViolation(
                        "unsupported_episode_count",
                        f"Episode count {value} in {text!r} does not match packet's episode_count",
                    )
                )
        for match in _RAW_SAMPLE_COUNT_PATTERN.finditer(text):
            value = int(match.group(1))
            if raw_count is None or value != raw_count:
                violations.append(
                    GroundingViolation(
                        "unsupported_sample_count",
                        f"Sample count {value} in {text!r} does not match packet's raw_count",
                    )
                )
    return violations


def check_typed_timing_claims(brief: ResearchBrief, packet: EvidencePacket) -> list[GroundingViolation]:
    """(#Phase 11.1 I) "earnings occurred 18h before setup" must be
    derivable (within a small tolerance) from the packet's own catalyst
    timestamps -- an invented offset is rejected even if some other,
    unrelated number in the packet happens to equal it."""
    catalyst = packet.catalyst_context
    nearest = catalyst.nearest_catalyst if catalyst is not None else None
    violations = []
    for text in _all_text(brief):
        for match in _TIMING_PATTERN.finditer(text):
            value = float(match.group(1))
            direction = match.group(2).lower()
            actual = (
                nearest.hours_before_setup if direction == "before" else nearest.hours_after_setup
            ) if nearest is not None else None
            if actual is None or abs(value - actual) > _TIMING_TOLERANCE_HOURS:
                violations.append(
                    GroundingViolation(
                        "unsupported_timing_claim",
                        f"Timing claim '{value}h {direction}' in {text!r} is not derivable "
                        "from catalyst timestamps",
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
        + check_typed_price_level_claims(brief, packet)
        + check_typed_episode_claims(brief, packet)
        + check_typed_timing_claims(brief, packet)
        + check_banned_language(brief)
    )
    return GroundingResult(is_valid=not violations, violations=violations)
