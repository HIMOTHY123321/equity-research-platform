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
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_analysis.research_brief import ResearchBrief
from app.ai_analysis.schemas import EvidencePacket
from app.database.models import Base, EvidencePacketRecord, ResearchBriefRecord


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
