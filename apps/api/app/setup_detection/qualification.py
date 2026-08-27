"""The single rule that separates a candidate from a qualified setup (#2,
#21): every hard EvidenceCheck must pass. Soft checks and conflicts are
always preserved as evidence but never independently block qualification --
a missing soft confirmation weakens a setup's evidence tree, it doesn't
erase the candidate.
"""

from __future__ import annotations

from app.setup_detection.schemas import EvidenceCheck


def is_qualified(hard_checks: list[EvidenceCheck]) -> bool:
    return all(check.passed for check in hard_checks)


def failed_hard_checks(hard_checks: list[EvidenceCheck]) -> list[EvidenceCheck]:
    return [check for check in hard_checks if not check.passed]


def satisfied_soft_count(soft_checks: list[EvidenceCheck]) -> int:
    return sum(1 for check in soft_checks if check.passed)
