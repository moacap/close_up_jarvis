"""Sales Farma Painel connector — syncs panel professional records from Sales Farma REST API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ConnectorRegistry

DEFAULT_SALES_FARMA_PAINEL_URL = (
    "https://demo.salesfarma.com.br/sincronia/api/profissional/160115"
)


def fetch_sales_farma_painel(
    url: str,
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """Fetch panel professional records from the configured Sales Farma Painel endpoint."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("GD_MED_REP", "data", "items", "results", "profissionais"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        return [data]
    return []


@ConnectorRegistry.register("sales_farma_painel")
class SalesFarmaPainelConnector(BaseConnector):
    """Sync medical/professional panel records from the Sales Farma Painel API."""

    connector_id = "sales_farma_painel"
    display_name = "Sales Farma Painel"
    auth_type = "local"

    def __init__(self, *, config_path: str | None = None) -> None:
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else get_config_dir() / "connectors" / "sales_farma_painel.json"
        )
        self._status = SyncStatus()

    def _load_config(self) -> Dict[str, str]:
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def configure(
        self,
        *,
        url: str = DEFAULT_SALES_FARMA_PAINEL_URL,
        token: str | None = None,
    ) -> None:
        """Validate endpoint reachability and persist connector config."""
        clean_url = url.strip() or DEFAULT_SALES_FARMA_PAINEL_URL
        if not clean_url.startswith(("https://", "http://")):
            raise ValueError("Sales Farma Painel URL must start with http:// or https://")
        clean_token = token.strip() if isinstance(token, str) else ""
        fetch_sales_farma_painel(clean_url, token=clean_token or None)
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
        """Yield Documents for each professional returned by Sales Farma Painel."""
        config = self._load_config()
        url = config.get("url") or DEFAULT_SALES_FARMA_PAINEL_URL
        token = config.get("token") or None
        records = fetch_sales_farma_painel(url, token=token)
        now_ts = datetime.now(timezone.utc)

        for idx, item in enumerate(records):
            prof_id = str(item.get("PROF_ID") or item.get("id") or idx).strip()
            rep_id = str(item.get("MERE_REP") or "").strip()
            nome = str(item.get("NOME") or item.get("name") or f"Profissional {prof_id}").strip()
            crm = str(item.get("MERE_CRM") or "").strip()
            uf_crm = str(item.get("MERE_UF_CRM") or "").strip()
            esp1 = str(item.get("MERE_ESP1") or "").strip()
            esp2 = str(item.get("MERE_ESP2") or "").strip()
            email = str(item.get("MERE_EMAIL") or "").strip()
            estab_id = str(item.get("ESTAB_ID") or "").strip()
            freq = str(item.get("MERE_FREQ") or "").strip()
            letra = str(item.get("MERE_LETRA") or "").strip()
            categoria = str(item.get("CATEGORIA_AUDIT") or "").strip()
            auditado = str(item.get("AUDITADO") or "").strip()
            obs = str(item.get("MERE_OBSREP") or "").strip()

            lines = [
                f"Nome: {nome}",
                f"PROF_ID: {prof_id}",
            ]
            if crm:
                lines.append(f"CRM: {crm}" + (f"/{uf_crm}" if uf_crm else ""))
            if rep_id:
                lines.append(f"Representante (MERE_REP): {rep_id}")
            if esp1 or esp2:
                esps = ", ".join(e for e in (esp1, esp2) if e)
                lines.append(f"Especialidade(s): {esps}")
            if estab_id:
                lines.append(f"Estabelecimento (ESTAB_ID): {estab_id}")
            if email:
                lines.append(f"E-mail: {email}")
            if freq or letra or categoria:
                lines.append(
                    f"Frequência: {freq or '-'} | Letra: {letra or '-'} | Categoria: {categoria or '-'}"
                )
            if auditado:
                lines.append(f"Auditado: {auditado}")
            if obs:
                lines.append(f"Observações: {obs}")

            yield Document(
                doc_id=f"sales-farma-painel-{rep_id or 'all'}-{prof_id}",
                source="sales_farma_painel",
                doc_type="professional",
                title=nome,
                content="\n".join(lines),
                author=rep_id or nome,
                timestamp=now_ts,
                url=url,
                metadata={
                    "prof_id": prof_id,
                    "rep_id": rep_id,
                    "crm": crm,
                    "uf_crm": uf_crm,
                    "esp1": esp1,
                    "esp2": esp2,
                    "estab_id": estab_id,
                    "email": email,
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now(timezone.utc)

    def sync_status(self) -> SyncStatus:
        return self._status


__all__ = [
    "DEFAULT_SALES_FARMA_PAINEL_URL",
    "SalesFarmaPainelConnector",
    "fetch_sales_farma_painel",
]
