"""Phase 11 (#C): optional development real-model provider. Only ever
constructed by app.api.deps.get_ai_analysis_provider when
`AI_ANALYSIS_PROVIDER=openai` and `OPENAI_API_KEY` is set (app/config.py) --
never hard-coded/selected anywhere else. No API key is committed anywhere in
this repository; a missing key raises AIAnalysisUnavailableError so the
product falls back to deterministic-only evidence rather than failing the
request (#C).

Its raw output is treated exactly as untrusted as any other provider's would
be: app.ai_analysis.brief.generate_research_brief independently re-validates
everything this class returns before it is ever served.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.ai_analysis.claims import EvidenceClaim
from app.ai_analysis.prompts import SYSTEM_PROMPT, build_research_brief_prompt
from app.ai_analysis.provider import AIAnalysisProvider, AIAnalysisUnavailableError
from app.ai_analysis.research_brief import RESEARCH_BRIEF_PROMPT_VERSION, AnalysisMode, ResearchBrief
from app.ai_analysis.schemas import EvidencePacket

_REQUEST_TIMEOUT_SECONDS = 30


class OpenAIAnalysisProvider(AIAnalysisProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise AIAnalysisUnavailableError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover -- openai is a declared dependency
            raise AIAnalysisUnavailableError("openai package is not installed") from exc

        self._model = model
        self._client = OpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS)

    def explain_setup(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        return self.synthesize_research_brief(packet, claims, AnalysisMode.WHY_THIS_SETUP).setup_explanation

    def summarize_contradictions(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        brief = self.synthesize_research_brief(packet, claims, AnalysisMode.WHY_NOT)
        parts = brief.contradictory_evidence + brief.uncertainty
        return "; ".join(parts)

    def generate_monitoring_summary(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> list[str]:
        return self.synthesize_research_brief(packet, claims, AnalysisMode.FULL).monitor_next

    def synthesize_research_brief(
        self, packet: EvidencePacket, claims: list[EvidenceClaim], mode: AnalysisMode
    ) -> ResearchBrief:
        prompt = build_research_brief_prompt(packet, claims, mode)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            payload = json.loads(content) if content else {}
        except Exception as exc:  # noqa: BLE001 -- any provider failure degrades to unavailable
            raise AIAnalysisUnavailableError(f"OpenAI request failed: {exc}") from exc

        return ResearchBrief(
            brief_id=f"{packet.packet_id}-{mode.value}-{self._model}",
            evidence_packet_id=packet.packet_id,
            mode=mode,
            situation_summary=str(payload.get("situation_summary", "")),
            setup_explanation=str(payload.get("setup_explanation", "")),
            supporting_evidence=list(payload.get("supporting_evidence", [])),
            contradictory_evidence=list(payload.get("contradictory_evidence", [])),
            catalyst_context=str(payload.get("catalyst_context", "")),
            historical_context=str(payload.get("historical_context", "")),
            uncertainty=list(payload.get("uncertainty", [])),
            invalidation_conditions=list(payload.get("invalidation_conditions", [])),
            monitor_next=list(payload.get("monitor_next", [])),
            evidence_refs=list(payload.get("evidence_refs", [])),
            generated_at=datetime.now(timezone.utc),
            as_of=packet.as_of,
            provider=self.name,
            model=self._model,
            prompt_version=RESEARCH_BRIEF_PROMPT_VERSION,
        )
