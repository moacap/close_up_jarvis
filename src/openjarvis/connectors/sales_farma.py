"""Sales Farma connector — syncs omni agent records from the Sales Farma REST API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ConnectorRegistry

DEFAULT_SALES_FARMA_URL = (
    "https://demo.salesfarma.com.br/sincronia/api/omni/agent"
)


def _parse_sales_farma_date(raw: Any) -> datetime:
    """Parse Sales Farma ``MM/DD/YYYY HH:MM:SS AM/PM`` timestamps (UTC-aware)."""
    if isinstance(raw, str) and raw.strip():
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def fetch_sales_farma_agents(
    url: str,
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """Fetch agent records from the configured Sales Farma endpoint."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "results", "agents"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        return [data]
    return []


@ConnectorRegistry.register("sales_farma")
class SalesFarmaConnector(BaseConnector):
    """Sync agent/representative records from the Sales Farma API."""

    connector_id = "sales_farma"
    display_name = "Sales Farma Propagandistas"
    auth_type = "local"

    def __init__(self, *, config_path: str | None = None) -> None:
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else get_config_dir() / "connectors" / "sales_farma.json"
        )
        self._status = SyncStatus()

    def _load_config(self) -> Dict[str, str]:
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def configure(
        self,
        *,
        url: str = DEFAULT_SALES_FARMA_URL,
        token: str | None = None,
    ) -> None:
        """Validate endpoint reachability and persist connector config."""
        clean_url = url.strip() or DEFAULT_SALES_FARMA_URL
        if not clean_url.startswith(("https://", "http://")):
            raise ValueError("Sales Farma URL must start with http:// or https://")
        clean_token = token.strip() if isinstance(token, str) else ""
        fetch_sales_farma_agents(clean_url, token=clean_token or None)
        from openjarvis.security.file_utils import secure_write_json

        payload: Dict[str, str] = {"url": clean_url}
        if clean_token:
            payload["token"] = clean_token
        secure_write_json(self._config_path, payload)

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
        """Yield Documents for each agent returned by Sales Farma."""
        config = self._load_config()
        url = config.get("url") or DEFAULT_SALES_FARMA_URL
        token = config.get("token") or None
        records = fetch_sales_farma_agents(url, token=token)

        for idx, item in enumerate(records):
            external_ref = str(item.get("external_ref") or idx)
            name = str(item.get("name") or f"Agente {external_ref}").strip()
            email = str(item.get("email") or "").strip()
            work_phone = str(item.get("work_phone") or "").strip()
            personal_phone = str(item.get("personal_phone") or "").strip()
            department = str(item.get("department") or "").strip()
            agent_type = str(item.get("agent_type") or "").strip()
            agent_type_desc = str(item.get("agent_type_description") or "").strip()
            status = str(item.get("status") or "").strip()
            lastdate_raw = item.get("lastdate")
            ts = _parse_sales_farma_date(lastdate_raw)

            if since is not None:
                since_cmp = (
                    since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
                )
                if ts < since_cmp:
                    continue

            lines = [
                f"Nome: {name}",
                f"Referência externa: {external_ref}",
            ]
            if department:
                lines.append(f"Departamento: {department}")
            if agent_type or agent_type_desc:
                lines.append(
                    f"Tipo: {agent_type_desc or agent_type}"
                    + (f" ({agent_type})" if agent_type and agent_type_desc else "")
                )
            if email:
                lines.append(f"E-mail: {email}")
            if work_phone:
                lines.append(f"Telefone comercial: {work_phone}")
            if personal_phone:
                lines.append(f"Telefone pessoal: {personal_phone}")
            if status:
                lines.append(f"Status: {status}")
            if lastdate_raw:
                lines.append(f"Última atualização: {lastdate_raw}")

            yield Document(
                doc_id=f"sales-farma-agent-{external_ref}",
                source="sales_farma",
                doc_type="agent",
                title=name,
                content="\n".join(lines),
                author=name,
                timestamp=ts,
                url=url,
                metadata={
                    "external_ref": external_ref,
                    "department": department,
                    "agent_type": agent_type,
                    "agent_type_description": agent_type_desc,
                    "email": email,
                    "status": status,
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now(timezone.utc)

    def sync_status(self) -> SyncStatus:
        return self._status


__all__ = [
    "DEFAULT_SALES_FARMA_URL",
    "SalesFarmaConnector",
    "fetch_sales_farma_agents",
]
