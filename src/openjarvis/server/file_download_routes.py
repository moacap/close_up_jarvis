"""FastAPI route for downloading files written by filesystem tools (file_write, pdf_generate, ...)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from openjarvis.security.file_policy import is_sensitive_file
from openjarvis.tools._paths import resolve_allowed_dirs

router = APIRouter(prefix="/v1/files", tags=["files"])


@router.get("/download")
async def download_file(path: str = Query(...)):
    """Serve a file for download, scoped to the configured allowed directories.

    Mirrors the containment check used by ``file_write``/``pdf_generate``
    (``tools/_paths.py``) so a request can only reach files those tools were
    themselves allowed to write.
    """
    allowed_dirs = [
        Path(d).expanduser().resolve() for d in resolve_allowed_dirs(None)
    ]
    candidate = Path(path).expanduser().resolve()

    # An empty allowed_dirs list means "no restriction configured" — the same
    # convention file_write/pdf_generate use (tools/_paths.py) — not "deny all".
    if allowed_dirs and not any(
        candidate == d or candidate.is_relative_to(d) for d in allowed_dirs
    ):
        raise HTTPException(status_code=403, detail="Path is outside allowed directories")
    if is_sensitive_file(candidate):
        raise HTTPException(status_code=403, detail="Access denied: sensitive file")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(candidate), filename=candidate.name)


__all__ = ["router"]
