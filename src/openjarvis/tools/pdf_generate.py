"""PDF generation tool — render text/simple-markdown content to a PDF file via fpdf2."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._paths import resolve_allowed_dirs
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Generated PDFs are documents, not data dumps — keep well under file_write's
# 10 MB text cap since a PDF of that size would already be unreasonable.
_MAX_CONTENT_CHARS = 500_000

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# fpdf2's core (non-embedded) fonts only support strict Latin-1 (ISO-8859-1).
# LLM-generated text routinely uses "smart" Unicode punctuation outside that
# range (em/en dashes, curly quotes, ellipsis, bullets, arrows) — normalize
# those to Latin-1-safe equivalents instead of letting the render crash.
_UNICODE_PUNCTUATION_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "•": "-",
    "→": "->", "←": "<-", " ": " ",
}


@ToolRegistry.register("pdf_generate")
class PDFGenerateTool(BaseTool):
    """Generate a PDF file from plain text or simple markdown content."""

    tool_id = "pdf_generate"

    def __init__(
        self,
        allowed_dirs: Optional[List[str]] = None,
    ) -> None:
        self._allowed_dirs = [
            Path(d).expanduser().resolve() for d in resolve_allowed_dirs(allowed_dirs)
        ]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="pdf_generate",
            description=(
                "Generate a PDF file from text content. Supports simple markdown:"
                " '# '/'## '/'### ' headings, '- ' bullet points, '**bold**' spans,"
                " and blank-line-separated paragraphs. Returns the path of the"
                " written PDF."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to write the PDF file to (should end in .pdf).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text or simple-markdown content to render.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional document title, rendered as a top heading.",
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": (
                            "Create parent directories if they"
                            " don't exist. Default: false."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
            category="filesystem",
            required_capabilities=["file:write"],
        )

    def _is_path_allowed(self, path: Path) -> bool:
        if not self._allowed_dirs:
            return True
        resolved = path.resolve()
        return any(
            resolved == d or resolved.is_relative_to(d) for d in self._allowed_dirs
        )

    def _render(self, pdf: Any, content: str, title: Optional[str]) -> None:
        from fpdf.enums import XPos, YPos

        def _line(height: int, text: str) -> None:
            pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        if title:
            pdf.set_font("Helvetica", "B", 18)
            _line(10, _latin1_safe(title))
            pdf.ln(4)

        heading_sizes = {1: 16, 2: 14, 3: 12}
        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if not line:
                pdf.ln(3)
                continue

            heading_match = _HEADING_RE.match(line)
            bullet_match = _BULLET_RE.match(line)

            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                pdf.set_font("Helvetica", "B", heading_sizes.get(level, 12))
                _line(8, _latin1_safe(text))
                pdf.ln(2)
                continue

            if bullet_match:
                text = bullet_match.group(1)
                pdf.set_font("Helvetica", "", 11)
                _line(6, _latin1_safe(f"-  {_strip_bold(text)}"))
                continue

            pdf.set_font("Helvetica", "", 11)
            _line(6, _latin1_safe(_strip_bold(line)))

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("path", "")
        if not file_path:
            return ToolResult(
                tool_name="pdf_generate", content="No path provided.", success=False
            )

        content = params.get("content")
        if content is None:
            return ToolResult(
                tool_name="pdf_generate", content="No content provided.", success=False
            )
        if len(content) > _MAX_CONTENT_CHARS:
            return ToolResult(
                tool_name="pdf_generate",
                content=(
                    f"Content too large: {len(content)} chars"
                    f" (max {_MAX_CONTENT_CHARS})."
                ),
                success=False,
            )

        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
        if not path.is_absolute() and self._allowed_dirs:
            path = self._allowed_dirs[0] / path

        from openjarvis.security.file_policy import is_sensitive_file

        if is_sensitive_file(path):
            return ToolResult(
                tool_name="pdf_generate",
                content=f"Access denied: {file_path} is a sensitive file.",
                success=False,
            )
        if not self._is_path_allowed(path):
            return ToolResult(
                tool_name="pdf_generate",
                content=f"Access denied: {file_path} is outside allowed directories.",
                success=False,
            )

        create_dirs = params.get("create_dirs", False)
        if create_dirs:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return ToolResult(
                    tool_name="pdf_generate",
                    content=f"Cannot create directories: {exc}",
                    success=False,
                )
        elif not path.parent.exists():
            return ToolResult(
                tool_name="pdf_generate",
                content=(
                    f"Parent directory does not exist: {path.parent}."
                    " Set create_dirs=true to create it."
                ),
                success=False,
            )

        try:
            from fpdf import FPDF
        except ImportError:
            return ToolResult(
                tool_name="pdf_generate",
                content="fpdf2 package not installed. Install with: pip install fpdf2",
                success=False,
            )

        try:
            pdf = FPDF()
            self._render(pdf, content, params.get("title"))
            pdf.output(str(path))
        except Exception as exc:
            return ToolResult(
                tool_name="pdf_generate",
                content=f"PDF generation error: {exc}",
                success=False,
            )

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        return ToolResult(
            tool_name="pdf_generate",
            content=f"Successfully wrote PDF to {path}",
            success=True,
            metadata={"path": str(path.resolve()), "size_bytes": size},
        )


def _strip_bold(text: str) -> str:
    """Drop ``**`` markers — fpdf2's core fonts have no easy inline bold spans."""
    return _BOLD_RE.sub(r"\1", text)


def _latin1_safe(text: str) -> str:
    """Normalize text to fit fpdf2's core-font Latin-1 encoding."""
    for char, replacement in _UNICODE_PUNCTUATION_MAP.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


__all__ = ["PDFGenerateTool"]
