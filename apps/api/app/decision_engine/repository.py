"""Persistence for DecisionPlan/DecisionTransition/ConditionEvaluation/
EvidenceDiffSnapshot -- same ABC + SqlAlchemy-implementation pattern as
every repository since Phase 7 (see app.forecasting.repository).

`save_plan` upserts the single current-state row for a plan (the plan's OWN
identity is mutable -- it moves through states -- but its condition
thresholds/entry rules never change once created, which `plan_builder.py`
enforces by construction, not by anything in this file). Transitions,
condition evaluations, and evidence-diff snapshots are strictly append-only:
no update/delete method exists for any of the three anywhere in this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Base,
    ConditionEvaluationRecord,
    DecisionPlanRecord,
    DecisionTransitionRecord,
    EvidenceDiffSnapshotRecord,
)
from app.decision_engine.schemas import (
    DecisionCondition,
    DecisionPlan,
    DecisionState,
    DecisionTransition,
    EvidenceDiffSnapshot,
)


class DecisionEngineRepository(ABC):
    @abstractmethod
    def save_plan(self, plan: DecisionPlan) -> str: ...

    @abstractmethod
    def get_plan(self, decision_plan_id: str) -> Optional[DecisionPlan]: ...

    @abstractmethod
    def list_plans(
        self,
        *,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        state: Optional[str] = None,
        open_only: bool = False,
        limit: int = 200,
    ) -> list[DecisionPlan]: ...

    @abstractmethod
    def record_transition(self, transition: DecisionTransition) -> str: ...

    @abstractmethod
    def list_transitions(self, decision_plan_id: str) -> list[DecisionTransition]: ...

    @abstractmethod
    def record_condition_evaluations(
        self, decision_plan_id: str, conditions: list[DecisionCondition]
    ) -> None: ...

    @abstractmethod
    def list_condition_evaluations(
        self, decision_plan_id: str, condition_id: str
    ) -> list[DecisionCondition]: ...

    @abstractmethod
    def record_evidence_diff(self, snapshot: EvidenceDiffSnapshot) -> str: ...

    @abstractmethod
    def list_evidence_diffs(self, decision_plan_id: str) -> list[EvidenceDiffSnapshot]: ...


_OPEN_STATES = [
    DecisionState.DETECTED.value,
    DecisionState.EVALUATING.value,
    DecisionState.WATCHING.value,
    DecisionState.ENTRY_CONDITIONS_MET.value,
    DecisionState.ACTIVE_THESIS.value,
    DecisionState.THESIS_STRENGTHENING.value,
    DecisionState.THESIS_WEAKENING.value,
]


class SqlAlchemyDecisionEngineRepository(DecisionEngineRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[
                DecisionPlanRecord.__table__,
                DecisionTransitionRecord.__table__,
                ConditionEvaluationRecord.__table__,
                EvidenceDiffSnapshotRecord.__table__,
            ],
            checkfirst=True,
        )

    def save_plan(self, plan: DecisionPlan) -> str:
        existing = self._session.execute(
            select(DecisionPlanRecord).where(DecisionPlanRecord.decision_plan_id == plan.decision_plan_id)
        ).scalar_one_or_none()
        payload = plan.model_dump(mode="json")
        if existing is not None:
            existing.state = plan.state.value
            existing.as_of = plan.as_of
            existing.payload = payload
        else:
            existing = DecisionPlanRecord(
                decision_plan_id=plan.decision_plan_id,
                symbol=plan.symbol,
                timeframe=plan.timeframe.value,
                setup_id=plan.setup_id,
                setup_type=plan.setup_type.value,
                direction=plan.direction.value,
                state=plan.state.value,
                created_at=plan.created_at,
                as_of=plan.as_of,
                payload=payload,
            )
            self._session.add(existing)
        self._session.commit()
        return plan.decision_plan_id

    def get_plan(self, decision_plan_id: str) -> Optional[DecisionPlan]:
        row = self._session.execute(
            select(DecisionPlanRecord).where(DecisionPlanRecord.decision_plan_id == decision_plan_id)
        ).scalar_one_or_none()
        return DecisionPlan.model_validate(row.payload) if row is not None else None

    def list_plans(
        self,
        *,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        state: Optional[str] = None,
        open_only: bool = False,
        limit: int = 200,
    ) -> list[DecisionPlan]:
        query = select(DecisionPlanRecord)
        if symbol is not None:
            query = query.where(DecisionPlanRecord.symbol == symbol)
        if timeframe is not None:
            query = query.where(DecisionPlanRecord.timeframe == timeframe)
        if state is not None:
            query = query.where(DecisionPlanRecord.state == state)
        if open_only:
            query = query.where(DecisionPlanRecord.state.in_(_OPEN_STATES))
        query = query.order_by(DecisionPlanRecord.created_at.desc()).limit(limit)
        rows = self._session.execute(query).scalars()
        return [DecisionPlan.model_validate(r.payload) for r in rows]

    def record_transition(self, transition: DecisionTransition) -> str:
        row = DecisionTransitionRecord(
            transition_id=transition.transition_id,
            decision_plan_id=transition.decision_plan_id,
            from_state=transition.from_state.value if transition.from_state else None,
            to_state=transition.to_state.value,
            occurred_at=transition.occurred_at,
            as_of=transition.as_of,
            payload=transition.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return transition.transition_id

    def list_transitions(self, decision_plan_id: str) -> list[DecisionTransition]:
        rows = self._session.execute(
            select(DecisionTransitionRecord)
            .where(DecisionTransitionRecord.decision_plan_id == decision_plan_id)
            .order_by(DecisionTransitionRecord.occurred_at.asc())
        ).scalars()
        return [DecisionTransition.model_validate(r.payload) for r in rows]

    def record_condition_evaluations(
        self, decision_plan_id: str, conditions: list[DecisionCondition]
    ) -> None:
        for condition in conditions:
            row = ConditionEvaluationRecord(
                decision_plan_id=decision_plan_id,
                condition_id=condition.id,
                status=condition.status.value,
                evaluated_at=condition.evaluated_at,
                payload=condition.model_dump(mode="json"),
            )
            self._session.add(row)
        self._session.commit()

    def list_condition_evaluations(self, decision_plan_id: str, condition_id: str) -> list[DecisionCondition]:
        rows = self._session.execute(
            select(ConditionEvaluationRecord)
            .where(
                ConditionEvaluationRecord.decision_plan_id == decision_plan_id,
                ConditionEvaluationRecord.condition_id == condition_id,
            )
            .order_by(ConditionEvaluationRecord.row_created_at.asc())
        ).scalars()
        return [DecisionCondition.model_validate(r.payload) for r in rows]

    def record_evidence_diff(self, snapshot: EvidenceDiffSnapshot) -> str:
        row = EvidenceDiffSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            decision_plan_id=snapshot.decision_plan_id,
            as_of=snapshot.as_of,
            classification=snapshot.classification.value,
            payload=snapshot.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return snapshot.snapshot_id

    def list_evidence_diffs(self, decision_plan_id: str) -> list[EvidenceDiffSnapshot]:
        rows = self._session.execute(
            select(EvidenceDiffSnapshotRecord)
            .where(EvidenceDiffSnapshotRecord.decision_plan_id == decision_plan_id)
            .order_by(EvidenceDiffSnapshotRecord.as_of.asc())
        ).scalars()
        return [EvidenceDiffSnapshot.model_validate(r.payload) for r in rows]
