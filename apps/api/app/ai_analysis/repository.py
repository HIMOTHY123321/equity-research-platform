"""Phase 11 (#K): persistence for EvidencePacket/ResearchBrief snapshots.
Same ABC + SqlAlchemy-implementation pattern as app.research_intelligence
.snapshots / app.news.repository -- callers depend only on
`EvidenceRepository`, never on SQLAlchemy directly. Both `save_packet`/
`save_brief` are idempotent on their deterministic business key
(`packet_id`/`brief_id`), matching the article/event upsert convention from
Phase 10: re-saving the same content is a no-op, never a duplicate row.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_analysis.research_brief import ResearchBrief
from app.ai_analysis.schemas import EvidencePacket
from app.database.models import Base, EvidencePacketRecord, ResearchBriefRecord


@dataclass(frozen=True)
class BriefListItem:
    """Hardening pass (§19): a lightweight read-model for the Reports page
    -- everything needed to render a list row without deserializing every
    brief's full JSON payload. `symbol`/`timeframe`/`setup_id` come from the
    EvidencePacket a brief is permanently bound to, joined by
    `evidence_packet_id` (never duplicated onto ResearchBrief itself, which
    has no symbol field of its own)."""

    brief_id: str
    evidence_packet_id: str
    symbol: str
    timeframe: str
    setup_id: Optional[str]
    mode: str
    provider: str
    model: Optional[str]
    prompt_version: str
    generated_at: datetime
    as_of: datetime


class EvidenceRepository(ABC):
    @abstractmethod
    def save_packet(self, packet: EvidencePacket) -> str: ...

    @abstractmethod
    def get_packet(self, packet_id: str) -> Optional[EvidencePacket]: ...

    @abstractmethod
    def save_brief(self, brief: ResearchBrief) -> str: ...

    @abstractmethod
    def get_brief(self, brief_id: str) -> Optional[ResearchBrief]: ...

    @abstractmethod
    def list_briefs_for_packet(self, evidence_packet_id: str, *, limit: int = 50) -> list[ResearchBrief]: ...

    @abstractmethod
    def list_recent_briefs(self, *, limit: int = 100) -> list["BriefListItem"]: ...


class SqlAlchemyEvidenceRepository(EvidenceRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        # Same SQLite local-dev bootstrap convention as every repository
        # since Phase 7 -- a no-op against an already-provisioned Postgres
        # database (docs/decisions/0008).
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[EvidencePacketRecord.__table__, ResearchBriefRecord.__table__],
            checkfirst=True,
        )

    def save_packet(self, packet: EvidencePacket) -> str:
        existing = self._session.execute(
            select(EvidencePacketRecord).where(EvidencePacketRecord.packet_id == packet.packet_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing.packet_id
        row = EvidencePacketRecord(
            packet_id=packet.packet_id,
            schema_version=packet.schema_version,
            symbol=packet.symbol,
            timeframe=packet.timeframe,
            setup_id=packet.setup.candidate.id if packet.setup is not None else None,
            as_of=packet.as_of,
            payload=packet.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return row.packet_id

    def get_packet(self, packet_id: str) -> Optional[EvidencePacket]:
        row = self._session.execute(
            select(EvidencePacketRecord).where(EvidencePacketRecord.packet_id == packet_id)
        ).scalar_one_or_none()
        return EvidencePacket.model_validate(row.payload) if row is not None else None

    def save_brief(self, brief: ResearchBrief) -> str:
        existing = self._session.execute(
            select(ResearchBriefRecord).where(ResearchBriefRecord.brief_id == brief.brief_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing.brief_id
        row = ResearchBriefRecord(
            brief_id=brief.brief_id,
            evidence_packet_id=brief.evidence_packet_id,
            mode=brief.mode.value,
            provider=brief.provider,
            model=brief.model,
            prompt_version=brief.prompt_version,
            grounding_rejected=brief.grounding_rejected,
            as_of=brief.as_of,
            payload=brief.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return row.brief_id

    def get_brief(self, brief_id: str) -> Optional[ResearchBrief]:
        row = self._session.execute(
            select(ResearchBriefRecord).where(ResearchBriefRecord.brief_id == brief_id)
        ).scalar_one_or_none()
        return ResearchBrief.model_validate(row.payload) if row is not None else None

    def list_briefs_for_packet(self, evidence_packet_id: str, *, limit: int = 50) -> list[ResearchBrief]:
        rows = self._session.execute(
            select(ResearchBriefRecord)
            .where(ResearchBriefRecord.evidence_packet_id == evidence_packet_id)
            .order_by(ResearchBriefRecord.created_at.desc())
            .limit(limit)
        ).scalars()
        return [ResearchBrief.model_validate(row.payload) for row in rows]

    def list_recent_briefs(self, *, limit: int = 100) -> list[BriefListItem]:
        rows = self._session.execute(
            select(ResearchBriefRecord, EvidencePacketRecord)
            .join(
                EvidencePacketRecord,
                EvidencePacketRecord.packet_id == ResearchBriefRecord.evidence_packet_id,
            )
            .order_by(ResearchBriefRecord.created_at.desc())
            .limit(limit)
        ).all()
        return [
            BriefListItem(
                brief_id=brief.brief_id,
                evidence_packet_id=brief.evidence_packet_id,
                symbol=packet.symbol,
                timeframe=packet.timeframe,
                setup_id=packet.setup_id,
                mode=brief.mode,
                provider=brief.provider,
                model=brief.model,
                prompt_version=brief.prompt_version,
                generated_at=_ensure_utc(
                    _parse_generated_at(brief.payload.get("generated_at"), brief.as_of)
                ),
                as_of=_ensure_utc(brief.as_of),
            )
            for brief, packet in rows
        ]


def _ensure_utc(value: datetime) -> datetime:
    """SQLite has no native timezone type: SQLAlchemy's `DateTime(timezone=True)`
    stores the instant correctly but returns a *naive* datetime on read-back
    (verified: a tz-aware UTC insert round-trips with `tzinfo=None`). Every
    value this repository writes is UTC to begin with (`packet.as_of`/
    `brief.as_of` are always UTC-aware at creation), so a naive read-back is
    re-tagged as UTC rather than left ambiguous -- leaving it naive caused the
    frontend to interpret the raw UTC digits as local wall-clock time, then
    apply a redundant EDT/EST conversion on top, producing an ~4h-shifted
    "Market as-of" timestamp on the Reports page."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse_generated_at(raw: Optional[str], fallback: datetime) -> datetime:
    if raw is None:
        return fallback
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return fallback
