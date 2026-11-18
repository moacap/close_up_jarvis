"""CoachingQI Visits connector — pulls visits from CoachingQI API and ingests webhook visit payloads."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ConnectorRegistry

DEFAULT_COACHINGQI_URL = "http://localhost:8001"
DEFAULT_COACHINGQI_TENANT = "achehomolog"


def _parse_visit_date(raw: Any) -> datetime:
    if isinstance(raw, str) and raw.strip():
        s = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def visit_payload_to_document(
    payload: Dict[str, Any],
    *,
    source_url: str = "",
) -> Document:
    """Convert a CoachingQI/TargetAI visit payload into a KnowledgeStore Document."""
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    vr = payload.get("visit_record") if isinstance(payload.get("visit_record"), dict) else {}
    if not vr and "visit_id" in payload:
        vr = payload

    visit_id = str(vr.get("visit_id") or payload.get("visit_id") or payload.get("id") or "unknown")
    rep_name = str(user.get("name") or "").strip()
    rep_id = str(user.get("id") or "").strip()
    contact_name = str(contact.get("contact_name") or "").strip()
    contact_id = str(contact.get("contact_id") or "").strip()

    spec = contact.get("contact_specialty")
    specialty = (
        spec.get("description") if isinstance(spec, dict) else str(spec or "")
    ).strip()
    target = contact.get("contact_target")
    target_desc = (
        target.get("description") if isinstance(target, dict) else str(target or "")
    ).strip()

    telemetry = vr.get("telemetry") if isinstance(vr.get("telemetry"), dict) else {}
    start_time = telemetry.get("start_time") or payload.get("created_at")
    ts = _parse_visit_date(start_time)

    visit_type = vr.get("visit_type")
    vtype_desc = (
        visit_type.get("description")
        if isinstance(visit_type, dict)
        else str(visit_type or "")
    ).strip()

    products = [
        str(p.get("name") or p.get("description") or "")
        for p in (vr.get("promoted_products") or [])
        if isinstance(p, dict)
    ]
    comments = str(vr.get("comments") or "").strip()
    next_goal = str(vr.get("next_visit_goal") or "").strip()

    lines = [f"Visita ID: {visit_id}"]
    if rep_name:
        lines.append(f"Representante: {rep_name}" + (f" ({rep_id})" if rep_id else ""))
    if contact_name:
        lines.append(
            f"Contato: {contact_name}"
            + (f" — {specialty}" if specialty else "")
            + (f" [Alvo: {target_desc}]" if target_desc else "")
        )
    if vtype_desc:
        lines.append(f"Tipo de visita: {vtype_desc}")
    if start_time:
        lines.append(f"Data/Hora: {start_time}")
    if products:
        lines.append(f"Produtos promovidos: {', '.join(p for p in products if p)}")
    if comments:
        lines.append(f"Relato da visita: {comments}")
    if next_goal:
        lines.append(f"Objetivo próxima visita: {next_goal}")

    title = f"Visita {visit_id}" + (f" — {contact_name}" if contact_name else "")
    return Document(
        doc_id=f"coachingqi-visit-{visit_id}",
        source="coachingqi_visits",
        doc_type="visit",
        title=title,
        content="\n".join(lines),
        author=rep_name or None,
        timestamp=ts,
        url=source_url or None,
        metadata={
            "visit_id": visit_id,
            "representative_id": rep_id,
            "representative_name": rep_name,
            "contact_id": contact_id,
            "contact_name": contact_name,
            "specialty": specialty,
            "target": target_desc,
            "products": [p for p in products if p],
        },
    )


def fetch_coachingqi_visits(
    base_url: str,
    *,
    tenant: str = DEFAULT_COACHINGQI_TENANT,
    token: str | None = None,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    """Fetch visits from a CoachingQI / TargetAI backend if reachable."""
    clean_base = base_url.strip().rstrip("/")
    headers: Dict[str, str] = {"Accept": "application/json", "X-Tenant": tenant}
    if token and token.strip():
        tok = token.strip()
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-API-Key"] = tok

    candidates = [
        f"{clean_base}/api/v1/targetqi/visits",
        f"{clean_base}/api/v1/{tenant}/visits",
        f"{clean_base}/api/v1/visits",
        f"{clean_base}/visits",
    ]
    for url in candidates:
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                for key in ("items", "visits", "data", "results"):
                    if isinstance(data.get(key), list):
                        return [item for item in data[key] if isinstance(item, dict)]
            return []
        except (httpx.HTTPError, ValueError):
            continue
    return []


@ConnectorRegistry.register("coachingqi_visits")
class CoachingQIVisitsConnector(BaseConnector):
    """Ingest and sync field visit records in the CoachingQI / TargetAI format."""

    connector_id = "coachingqi_visits"
    display_name = "CoachingQI Visitas"
    auth_type = "local"

    def __init__(self, *, config_path: str | None = None) -> None:
        base_dir = get_config_dir() / "connectors"
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else base_dir / "coachingqi_visits.json"
        )
        self._inbox_path = self._config_path.parent / "coachingqi_visits_inbox.jsonl"
        self._status = SyncStatus()

    def _load_config(self) -> Dict[str, str]:
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def configure(
        self,
        *,
        url: str = DEFAULT_COACHINGQI_URL,
        tenant: str = DEFAULT_COACHINGQI_TENANT,
        token: str | None = None,
    ) -> None:
        clean_url = url.strip().rstrip("/") or DEFAULT_COACHINGQI_URL
        if not clean_url.startswith(("https://", "http://")):
            raise ValueError("CoachingQI URL must start with http:// or https://")
        clean_tenant = tenant.strip() or DEFAULT_COACHINGQI_TENANT
        clean_token = token.strip() if isinstance(token, str) else ""

        from openjarvis.security.file_utils import secure_write_json

        payload: Dict[str, str] = {"url": clean_url, "tenant": clean_tenant}
        if clean_token:
            payload["token"] = clean_token
        secure_write_json(self._config_path, payload)

    def append_visit(self, payload: Dict[str, Any]) -> Document:
        """Persist a pushed visit payload to the local inbox and return its Document."""
        self._inbox_path.parent.mkdir(parents=True, exist_ok=True)
        with self._inbox_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return visit_payload_to_document(payload)

    def is_connected(self) -> bool:
        if not self._config_path.exists():
            return False
        try:
            data = self._load_config()
            return bool(data.get("url"))
        except (json.JSONDecodeError, OSError, TypeError):
            return False

    def disconnect(self) -> None:
        if self._config_path.exists():
            self._config_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents from remote CoachingQI API (if configured) + local webhook inbox."""
        config = self._load_config() if self._config_path.exists() else {}
        url = config.get("url", DEFAULT_COACHINGQI_URL)
        tenant = config.get("tenant", DEFAULT_COACHINGQI_TENANT)
        token = config.get("token") or None

        seen_ids: set[str] = set()
        records: List[Dict[str, Any]] = []
        if url:
            records.extend(fetch_coachingqi_visits(url, tenant=tenant, token=token))

        if self._inbox_path.exists():
            for raw in self._inbox_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                except json.JSONDecodeError:
                    continue

        since_cmp = (
            since if (since is None or since.tzinfo is not None) else since.replace(tzinfo=timezone.utc)
        )
        for rec in records:
            doc = visit_payload_to_document(rec, source_url=url)
            if doc.doc_id in seen_ids:
                continue
            seen_ids.add(doc.doc_id)
            if since_cmp is not None and doc.timestamp is not None and doc.timestamp < since_cmp:
                continue
            yield doc

        self._status.state = "idle"
        self._status.last_sync = datetime.now(timezone.utc)

    def sync_status(self) -> SyncStatus:
        return self._status


def _forward_to_targetqi(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Forward ingested visits to the configured TargetQI webhook when connected."""
    connector = CoachingQIVisitsConnector()
    if not connector.is_connected():
        return []
    cfg = connector._load_config()
    base_url = cfg.get("url", "").strip().rstrip("/")
    if not base_url:
        return []
    tenant = cfg.get("tenant", DEFAULT_COACHINGQI_TENANT).strip() or DEFAULT_COACHINGQI_TENANT
    token = cfg.get("token", "").strip()
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "X-Tenant": tenant,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token

    if "/webhook" in base_url or base_url.endswith(("/visit-record", "/visitas")):
        webhook_url = base_url
    else:
        webhook_url = f"{base_url}/api/v1/targetqi/visitas"
    outcomes: List[Dict[str, Any]] = []
    for item in items:
        try:
            resp = httpx.post(webhook_url, json=item, headers=headers, timeout=60.0)
            out: Dict[str, Any] = {"url": webhook_url, "status_code": resp.status_code}
            if resp.status_code >= 400:
                out["response"] = resp.text[:300]
            outcomes.append(out)
        except httpx.HTTPError as exc:
            outcomes.append({"url": webhook_url, "error": str(exc)})
    return outcomes


def ingest_visit_records(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist, index in KnowledgeStore, and forward to TargetQI if configured."""
    from openjarvis.connectors.pipeline import IngestionPipeline
    from openjarvis.connectors.store import KnowledgeStore

    connector = CoachingQIVisitsConnector()
    docs = [connector.append_visit(item) for item in items]
    with KnowledgeStore() as store:
        IngestionPipeline(store=store).ingest(docs)
    forwarded = _forward_to_targetqi(items)
    return {
        "status": "ok",
        "ingested": len(docs),
        "visit_ids": [d.metadata.get("visit_id") for d in docs],
        "targetqi_forwarded": forwarded,
    }


__all__ = [
    "CoachingQIVisitsConnector",
    "DEFAULT_COACHINGQI_TENANT",
    "DEFAULT_COACHINGQI_URL",
    "fetch_coachingqi_visits",
    "ingest_visit_records",
    "visit_payload_to_document",
]
