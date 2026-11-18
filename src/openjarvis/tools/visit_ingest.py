"""Visit ingestion tool — register CoachingQI/TargetQI visits directly from chat."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("visit_ingest")
class VisitIngestTool(BaseTool):
    """Register and index a field visit record in the CoachingQI/TargetAI format."""

    tool_id = "visit_ingest"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="visit_ingest",
            description=(
                "Register and index a field visit (visita) in the CoachingQI Visitas "
                "store (equivalent to POST /targetqi/visit-record). Use whenever the "
                "user asks to register, log, or record a representative's visit to a doctor/contact."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "visit_id": {
                        "type": "string",
                        "description": "Unique visit ID (generated automatically if omitted).",
                    },
                    "representative_name": {
                        "type": "string",
                        "description": "Sales representative name.",
                    },
                    "representative_id": {
                        "type": "string",
                        "description": "Optional representative ID.",
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Doctor / contact name.",
                    },
                    "contact_id": {
                        "type": "string",
                        "description": "Optional doctor / contact ID.",
                    },
                    "specialty": {
                        "type": "string",
                        "description": "Medical specialty (e.g. Cardiologia).",
                    },
                    "target": {
                        "type": "string",
                        "description": "Contact target tier (e.g. Ouro, Prata).",
                    },
                    "visit_type": {
                        "type": "string",
                        "description": "Visit type (e.g. PRESENCIAL, REMOTA). Default: PRESENCIAL.",
                    },
                    "product": {
                        "type": "string",
                        "description": "Promoted product name(s).",
                    },
                    "comments": {
                        "type": "string",
                        "description": "Visit report / clinical notes.",
                    },
                    "next_visit_goal": {
                        "type": "string",
                        "description": "Goal for the next visit.",
                    },
                },
                "required": ["contact_name", "comments"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.coachingqi_visits import ingest_visit_records

        import hashlib

        visit_id = str(params.get("visit_id") or "").strip() or f"SF-{uuid.uuid4().hex[:8].upper()}"
        rep_name = str(params.get("representative_name") or "").strip()
        rep_id = str(params.get("representative_id") or "").strip()
        contact_name = str(params.get("contact_name") or "").strip()
        contact_id = str(params.get("contact_id") or "").strip()
        specialty = str(params.get("specialty") or "").strip()
        target = str(params.get("target") or "").strip()
        visit_type = str(params.get("visit_type") or "PRESENCIAL").strip()
        product = str(params.get("product") or "").strip()
        comments = str(params.get("comments") or "").strip()
        next_goal = str(params.get("next_visit_goal") or "").strip()

        if not contact_name or not comments:
            return ToolResult(
                tool_name="visit_ingest",
                content="Both 'contact_name' and 'comments' are required.",
                success=False,
            )

        if not rep_id:
            seed = rep_name or "default-rep"
            rep_id = f"USR-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:9].upper()}"
        if not contact_id:
            contact_id = str(int(hashlib.sha1(contact_name.encode("utf-8")).hexdigest()[:7], 16))

        products = [
            {"name": p.strip()}
            for p in product.split(",")
            if p.strip()
        ]
        payload: Dict[str, Any] = {
            "user": {"id": rep_id, "name": rep_name},
            "contact": {
                "contact_id": contact_id,
                "contact_name": contact_name,
                "contact_specialty": {"description": specialty},
                "contact_target": {"description": target},
            },
            "visit_record": {
                "visit_id": visit_id,
                "visit_type": {"description": visit_type},
                "promoted_products": products,
                "comments": comments,
                "next_visit_goal": next_goal,
            },
        }
        result = ingest_visit_records([payload])
        return ToolResult(
            tool_name="visit_ingest",
            content=(
                f"Visita {visit_id} registrada e indexada com sucesso "
                f"(contato: {contact_name}, status: {result.get('status')})."
            ),
            success=True,
            metadata=result,
        )


__all__ = ["VisitIngestTool"]
