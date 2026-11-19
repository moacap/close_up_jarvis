"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
import weakref
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openjarvis.core.paths import get_config_dir
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.server.model_capabilities import is_embed_only_model
from openjarvis.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_calls=[
                    ToolCall(
                        id=tool_call.get("id", ""),
                        name=tool_call.get("function", {}).get("name", ""),
                        arguments=tool_call.get("function", {}).get("arguments", "{}"),
                    )
                    for tool_call in (m.tool_calls or [])
                ]
                or None,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


_CONNECTOR_QUERY_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("news_rss", re.compile(r"\b(rss|feeds?|not[íi]cias?|news|labroots)\b", re.I), 10),
    ("apple_contacts", re.compile(r"\b(contatos?|contacts?|telefone|e-?mail|apple\s*contacts)\b", re.I), 25),
    ("apple_calendar", re.compile(r"\b(calend[áa]rio|calendar|agenda|reuni[ãõa]o|reuni[õo]es|compromissos?|eventos?)\b", re.I), 25),
    ("apple_notes", re.compile(r"\b(notas?|notes?|anota[çc][ãõo]es?|apple\s*notes)\b", re.I), 20),
    ("imessage", re.compile(r"\b(imessage|mensagens?|sms)\b", re.I), 20),
    ("sales_farma_painel", re.compile(r"\b(painel|profissional|profissionais|crm|m[ée]dicos?|sales\s*farma\s*painel)\b", re.I), 25),
)


def _build_connector_context(messages: list[Message]) -> str:
    """Return KnowledgeStore records for connected sources mentioned in the last user message."""
    last_user = next((m.text for m in reversed(messages) if m.role == Role.USER and m.text), "")
    if not last_user:
        return ""

    matched = [
        (src, limit)
        for src, pat, limit in _CONNECTOR_QUERY_PATTERNS
        if pat.search(last_user)
    ]
    if not matched:
        return ""

    sections: list[str] = []
    try:
        from openjarvis.connectors.store import KnowledgeStore
        from openjarvis.core.paths import get_config_dir

        with KnowledgeStore() as store:
            for src, limit in matched:
                if src == "news_rss":
                    cfg_path = get_config_dir() / "connectors" / "news_rss.json"
                    if cfg_path.exists():
                        try:
                            feeds = json.loads(cfg_path.read_text(encoding="utf-8")).get("feeds", [])
                            if feeds:
                                feed_lines = ", ".join(
                                    f"{f.get('name', '')} ({f.get('url', '')})" for f in feeds
                                )
                                sections.append(f"Feeds RSS configurados: {feed_lines}")
                        except Exception:
                            pass
                rows = store._conn.execute(
                    "SELECT title, content, url, timestamp FROM knowledge_chunks "
                    "WHERE source = ? ORDER BY rowid DESC LIMIT ?",
                    (src, limit),
                ).fetchall()
                if rows:
                    lines = []
                    for title, content, url, ts in rows:
                        snippet = (content or "").strip().replace("\n", " ")[:350]
                        part = f"- {title or '(sem título)'}"
                        if ts:
                            part += f" [{ts}]"
                        if snippet:
                            part += f": {snippet}"
                        if url:
                            part += f" ({url})"
                        lines.append(part)
                    sections.append(f"Dados indexados de `{src}`:\n" + "\n".join(lines))
    except Exception:
        return ""

    return "\n\n".join(sections)


def _ensure_identity_prompt(messages: list[Message], app_config) -> list[Message]:
    """Return one leading system message, adding identity when needed.

    The desktop UI's chat backend posts only user/assistant turns to
    ``/v1/chat/completions`` (see ``frontend/.../Chat/InputArea.tsx``), so
    nothing grounds the model's identity. Without a system prompt the model
    answers from its training identity (e.g. "I'm Claude", "I am Qwen"),
    which is what #540 reported. The CLI paths inject this via
    ``SystemPromptBuilder`` / ``BaseAgent``; the engine-direct server paths
    did not. This mirrors the agent fallback in ``agents/_stubs.py``.

    If any caller-supplied message already carries a system role, the caller
    has supplied their own grounding and we do not add the server identity.
    All system messages are still folded into one leading entry because some
    chat templates reject multiple or mid-history system roles. Internally
    tagged memory context does not count as caller grounding.

    Resolution of the identity text: the config comes from ``app.state`` when
    wired, otherwise ``load_config()``; the prompt itself is assembled by
    ``SystemPromptBuilder`` from ``agent.default_system_prompt`` plus the
    persona files (SOUL.md/MEMORY.md/USER.md), matching
    ``_build_managed_system_prompt`` in ``agent_manager_routes.py``. Config
    resolution is wrapped so a broken/missing config degrades to "no
    injection" rather than crashing the endpoint, but the failure is logged
    (per REVIEW.md — never silently swallow).
    """

    def _is_caller_system_prompt(m: Message) -> bool:
        return m.role == Role.SYSTEM and not m.metadata.get("memory_context")

    system_messages = [message for message in messages if message.role == Role.SYSTEM]
    caller_supplied_system = any(
        _is_caller_system_prompt(message) for message in system_messages
    )
    identity_already_applied = any(
        message.metadata.get("openjarvis_identity_prompt")
        for message in system_messages
    )

    prompt = ""
    if not caller_supplied_system and not identity_already_applied:
        try:
            cfg = app_config
            if cfg is None:
                from openjarvis.core.config import load_config

                cfg = load_config()

            from openjarvis.prompt.builder import SystemPromptBuilder

            builder = SystemPromptBuilder(
                agent_template=cfg.agent.default_system_prompt or "",
                memory_files_config=getattr(cfg, "memory_files", None),
                system_prompt_config=getattr(cfg, "system_prompt", None),
            )
            prompt = builder.build()
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Identity system prompt resolution failed; "
                "serving request without identity grounding",
                exc_info=True,
            )

    system_parts = []
    if prompt:
        system_parts.append(prompt)
    system_parts.append(
        "Fontes de dados conectadas (KnowledgeStore): use `knowledge_sql` "
        "(ex.: `SELECT title, content, url, timestamp FROM knowledge_chunks "
        "WHERE source = 'news_rss' ORDER BY timestamp DESC LIMIT 10`) ou "
        "`knowledge_search` para consultar documentos sincronizados por `source`: "
        "`news_rss` (News / RSS, config em `~/.openjarvis/connectors/news_rss.json`), "
        "`sales_farma` (Sales Farma Propagandistas), `coachingqi_visits` (TagetIQ), "
        "`apple_calendar`, `apple_contacts`, `apple_notes` e `imessage`. "
        "NUNCA use `shell_exec` para procurar arquivos de configuração de conectores; "
        "consulte diretamente `knowledge_sql` ou `knowledge_search`."
    )
    connector_ctx = _build_connector_context(messages)
    if connector_ctx:
        system_parts.append(connector_ctx)
    system_parts.extend(message.text for message in system_messages if message.text)
    non_system_messages = [
        message for message in messages if message.role != Role.SYSTEM
    ]

    if not system_parts:
        return non_system_messages

    if system_messages:
        first_system = system_messages[0]
        metadata = dict(first_system.metadata)
        if prompt:
            # Preserve the first system message's metadata while tagging the
            # server-built identity so BaseAgent does not build it a second
            # time if this normalized conversation later reaches agent code.
            metadata["openjarvis_identity_prompt"] = True
        combined_system = replace(
            first_system,
            content="\n\n".join(system_parts),
            metadata=metadata,
        )
    else:
        combined_system = Message(
            role=Role.SYSTEM,
            content=prompt,
            metadata={"openjarvis_identity_prompt": True},
        )

    return [combined_system, *non_system_messages]


def _scripts_dir():
    """Return the directory where customizable slash-command scripts live."""
    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / "scripts"


def _is_valid_script_name(name: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", name))


def _extract_script_params(script_path) -> list[dict[str, str]]:
    """Extract ``--flag`` options and help strings from ``argparse`` calls via AST."""
    import ast

    params: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_add_arg = (
                isinstance(func, ast.Attribute) and func.attr == "add_argument"
            )
            if not is_add_arg:
                continue
            flags = [
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("--")
            ]
            help_text = ""
            for kw in node.keywords:
                if (
                    kw.arg == "help"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    help_text = kw.value.value
                    break
            for flag in flags:
                if flag not in seen:
                    seen.add(flag)
                    params.append({"flag": flag, "help": help_text})
    except Exception:
        pass
    if "--help" not in seen:
        params.append({"flag": "--help", "help": "Mostrar ajuda e parâmetros do script"})
    return params


def _list_custom_scripts() -> list[dict[str, Any]]:
    sdir = _scripts_dir()
    if not sdir.exists():
        return []
    items = []
    for p in sorted(sdir.glob("*.py")):
        if _is_valid_script_name(p.stem):
            stat = p.stat()
            items.append(
                {
                    "name": p.stem,
                    "command": f"@{p.stem}",
                    "path": str(p),
                    "size_bytes": stat.st_size,
                    "params": _extract_script_params(p),
                }
            )
    return items


def _execute_custom_script(name: str, args_str: str = "") -> dict[str, Any]:
    """Execute ``~/.openjarvis/scripts/<name>.py`` with optional CLI args."""
    import shlex
    import subprocess
    import sys

    if not _is_valid_script_name(name):
        raise HTTPException(status_code=400, detail="Invalid script name")
    script_path = _scripts_dir() / f"{name}.py"
    if not script_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script '@{name}' not found")

    cmd = [sys.executable, str(script_path)]
    if args_str.strip():
        cmd.extend(shlex.split(args_str))

    proc = subprocess.run(
        cmd,
        cwd=str(_scripts_dir()),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "name": name,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _format_script_reply(res: dict[str, Any]) -> str:
    out = (res.get("stdout") or "").strip()
    err = (res.get("stderr") or "").strip()
    code = res.get("exit_code", 0)
    name = res["name"]

    if code != 0:
        parts = [f"Não consegui executar **@{name}** corretamente (código `{code}`)."]
        if err:
            parts.append(f"Detalhes do erro:\n```\n{err}\n```")
        elif out:
            parts.append(f"Saída:\n```\n{out}\n```")
        return "\n\n".join(parts)

    if not out:
        return f"Pronto! **@{name}** foi executado com sucesso."

    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if out.startswith(("{", "[")):
        body = f"```json\n{out}\n```"
    elif len(lines) == 1:
        body = lines[0]
    else:
        body = "\n".join(f"- {line}" for line in lines)

    parts = [f"Aqui está o resultado de **@{name}** ({len(lines)} {'registro' if len(lines) == 1 else 'registros'}):", body]
    if err:
        parts.append(f"Observação:\n```\n{err}\n```")
    return "\n\n".join(parts)


async def _maybe_handle_slash_script(request_body: ChatCompletionRequest):
    """Handle ``@scripts`` / ``@<nome>`` direct calls, or enrich inline ``@<nome>`` refs."""
    last_user = ""
    last_user_idx = -1
    for idx in range(len(request_body.messages) - 1, -1, -1):
        m = request_body.messages[idx]
        if m.role == "user" and m.content:
            last_user = m.content.strip()
            last_user_idx = idx
            break
    if not last_user:
        return None

    # Case 1: message starts with @scripts or @<script> -> run directly.
    if last_user.startswith("@"):
        parts = last_user.split(None, 1)
        cmd = parts[0]
        args_str = parts[1] if len(parts) > 1 else ""
        name = cmd[1:]

        if cmd == "@scripts":
            scripts = _list_custom_scripts()
            if not scripts:
                reply_text = (
                    "Nenhum script customizável encontrado em `~/.openjarvis/scripts/`.\n\n"
                    "Peça no chat para criar um script Python (ex.: *\"Crie um script chamado `meu_script` que ...\"*) "
                    "e depois execute com `@meu_script`."
                )
            else:
                lines = ["**Scripts customizáveis disponíveis:**"]
                for s in scripts:
                    lines.append(f"- `{s['command']}` (`{s['path']}`)")
                reply_text = "\n".join(lines)
        elif _is_valid_script_name(name) and (_scripts_dir() / f"{name}.py").is_file():
            res = await asyncio.to_thread(_execute_custom_script, name, args_str)
            reply_text = _format_script_reply(res)
        else:
            return None

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = request_body.model
        if request_body.stream:
            async def _stream_reply():
                first = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
                )
                yield f"data: {first.model_dump_json()}\n\n"
                content = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[StreamChoice(delta=DeltaMessage(content=reply_text))],
                )
                yield f"data: {content.model_dump_json()}\n\n"
                done = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
                )
                yield f"data: {done.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                _stream_reply(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        return ChatCompletionResponse(
            id=chunk_id,
            model=model,
            choices=[
                Choice(
                    message=ChoiceMessage(role="assistant", content=reply_text),
                    finish_reason="stop",
                )
            ],
        )

    # Case 2: inline @<script> [args...] inside a natural-language prompt.
    # Execute the referenced script and attach its output so the LLM formats it.
    import re

    match = re.search(r"@([A-Za-z0-9_-]+)(.*)$", last_user)
    if match and last_user_idx >= 0:
        name = match.group(1)
        args_str = match.group(2).strip()
        if _is_valid_script_name(name) and (_scripts_dir() / f"{name}.py").is_file():
            res = await asyncio.to_thread(_execute_custom_script, name, args_str)
            formatted = _format_script_reply(res)
            request_body.messages[last_user_idx].content = (
                f"{last_user}\n\n[Resultado real da execução de @{name}]:\n{formatted}"
            )
    return None


@router.post("/targetqi/visit-record")
@router.post("/api/v1/targetqi/visit-record")
async def ingest_targetqi_visit_record(request: Request):
    """Ingest a CoachingQI/TargetQI visit record payload into KnowledgeStore."""
    from openjarvis.connectors.coachingqi_visits import ingest_visit_records

    body = await request.json()
    items = body if isinstance(body, list) else [body]
    valid = [item for item in items if isinstance(item, dict)]
    if not valid:
        raise HTTPException(status_code=400, detail="Visit JSON object or array is required")
    return await asyncio.to_thread(ingest_visit_records, valid)


@router.get("/v1/scripts")
async def list_scripts_endpoint():
    """List customizable Python scripts in ``~/.openjarvis/scripts/``."""
    return {"scripts": _list_custom_scripts()}


def _build_scripts_openapi_schema(request: Request, only_name: str | None = None) -> dict[str, Any]:
    """Build OpenAPI 3.1 schema for all scripts or a single named script."""
    scripts = _list_custom_scripts()
    if only_name is not None:
        clean = only_name.strip().lstrip("@/")
        scripts = [s for s in scripts if s["name"] == clean]
        if not scripts:
            raise HTTPException(status_code=404, detail=f"Script '@{clean}' not found")
    paths: dict[str, Any] = {}
    if only_name is None:
        paths["/v1/scripts"] = {
            "get": {
                "tags": ["Scripts"],
                "summary": "Listar scripts customizáveis",
                "responses": {"200": {"description": "Lista de scripts e parâmetros"}},
            }
        }
    for s in scripts:
        name = s["name"]
        params_spec = [
            {
                "name": p["flag"].lstrip("-"),
                "in": "query",
                "required": False,
                "description": p.get("help") or f"Parâmetro {p['flag']}",
                "schema": {"type": "string"},
            }
            for p in s.get("params", [])
            if p.get("flag") != "--help"
        ]
        params_spec.append(
            {
                "name": "args",
                "in": "query",
                "required": False,
                "description": "Argumentos CLI completos (ex.: --texto sales --com-cargo)",
                "schema": {"type": "string"},
            }
        )
        paths[f"/v1/scripts/{name}/run"] = {
            "get": {
                "tags": [name],
                "summary": f"Executar {name} (GET)",
                "parameters": params_spec,
                "responses": {
                    "200": {
                        "description": "Resultado JSON com o campo data",
                    }
                },
            },
            "post": {
                "tags": [name],
                "summary": f"Executar {name} (POST)",
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "args": {
                                        "type": "string",
                                        "example": "--texto sales",
                                    }
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Resultado JSON com o campo data",
                    }
                },
            },
        }
    title = (
        f"Close-UP — API do Script {only_name}"
        if only_name
        else "Close-UP — Scripts Customizáveis API"
    )
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": "Documentação específica dos endpoints gerados para os scripts em ~/.openjarvis/scripts/.",
        },
        "servers": [{"url": str(request.base_url).rstrip("/")}],
        "paths": paths,
    }


@router.get("/v1/scripts/openapi.json", include_in_schema=False)
async def scripts_openapi_schema(request: Request):
    """Dynamic OpenAPI schema dedicated specifically to customizable script APIs."""
    return _build_scripts_openapi_schema(request)


@router.get("/v1/scripts/{name}/openapi.json", include_in_schema=False)
async def single_script_openapi_schema(name: str, request: Request):
    """Dynamic OpenAPI schema for a single customizable script."""
    return _build_scripts_openapi_schema(request, only_name=name)


def _render_scripts_docs_html(only_name: str | None = None) -> str:
    import json as _json

    title = (
        f"Close-UP — API do Script {only_name}"
        if only_name
        else "Close-UP — Scripts Customizáveis API Docs"
    )
    heading = (
        f"API do Script — <code>{only_name}</code>"
        if only_name
        else "Scripts Customizáveis — API Docs"
    )
    openapi_href = (
        f"/v1/scripts/{only_name}/openapi.json"
        if only_name
        else "/v1/scripts/openapi.json"
    )
    only_json = _json.dumps(only_name)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    :root {{ --bg:#0f1117; --card:#171a23; --border:#2a2f3d; --text:#e6e8ef; --muted:#9aa3b2; --accent:#6366f1; --get:#10b981; --post:#3b82f6; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); padding:28px 20px; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 6px; }}
    .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 22px; }}
    .sub a {{ color: #818cf8; text-decoration: none; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 18px; overflow: hidden; }}
    .card-hd {{ padding: 14px 18px; border-bottom: 1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }}
    .card-title {{ font-weight: 600; font-size: 15px; font-family: ui-monospace, monospace; }}
    .card-body {{ padding: 16px 18px; }}
    .ep {{ display:flex; align-items:center; gap:10px; margin-bottom: 14px; font-family: ui-monospace, monospace; font-size: 13px; }}
    .badge {{ padding: 3px 8px; border-radius: 5px; font-weight: 700; font-size: 11px; color: #fff; }}
    .badge.get {{ background: var(--get); }}
    .badge.post {{ background: var(--post); }}
    .params {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .field label {{ display:block; font-size: 11px; color: var(--muted); margin-bottom: 4px; font-family: ui-monospace, monospace; }}
    .field input {{ width:100%; padding: 7px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 12px; font-family: ui-monospace, monospace; }}
    .hint {{ font-size: 11px; color: var(--muted); margin-top: 3px; }}
    .actions {{ display:flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    button {{ padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: 12px; font-weight: 600; }}
    .btn-primary {{ background: var(--accent); color: #fff; }}
    .btn-sec {{ background: #232837; color: var(--text); border: 1px solid var(--border); }}
    pre {{ background: #0b0d12; border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-size: 12px; overflow-x: auto; margin: 12px 0 0; line-height: 1.45; }}
    .curl-box {{ color: #a5b4fc; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{heading}</h1>
    <div class="sub">
      Documentação interativa ·
      <a href="{openapi_href}" target="_blank">OpenAPI JSON</a>
      {" · <a href='/v1/scripts/docs'>Ver todos os scripts</a>" if only_name else ""}
    </div>
    <div id="app">Carregando scripts...</div>
  </div>
  <script>
    const ONLY_NAME = {only_json};
    async function load() {{
      const res = await fetch('/v1/scripts');
      const json = await res.json();
      let scripts = json.scripts || [];
      if (ONLY_NAME) scripts = scripts.filter(s => s.name === ONLY_NAME);
      const app = document.getElementById('app');
      if (!scripts.length) {{
        app.innerHTML = '<div class="card"><div class="card-body">Script não encontrado em ~/.openjarvis/scripts/.</div></div>';
        return;
      }}
      app.innerHTML = '';
      for (const s of scripts) {{
        const card = document.createElement('div');
        card.className = 'card';
        const params = (s.params || []).filter(p => p.flag !== '--help');
        const guessPlaceholder = (key, helpText) => {{
          const m = (helpText || '').match(/(?:por exemplo|exemplo|ex\.?)\s*:\s*([^\\r\\n,;]+)/i);
          if (m && m[1]) return `ex: ${{m[1].trim()}}`;
          if (key.startsWith('com-') || key.startsWith('sem-') || key.startsWith('no-')) return 'ex: true';
          if (key === 'texto') return 'ex: sales';
          if (key === 'cargo') return 'ex: PROPAGANDISTA MEDICO (REP)';
          return `ex: valor para ${{key}}`;
        }};
        const fieldsHtml = params.map(p => {{
          const key = p.flag.replace(/^--/, '');
          const ph = guessPlaceholder(key, p.help);
          return `<div class="field">
            <label>${{key}}</label>
            <input type="text" data-param="${{key}}" placeholder="${{ph}}" />
            <div class="hint">${{p.help || ''}}</div>
          </div>`;
        }}).join('') + `<div class="field">
          <label>args (opcional)</label>
          <input type="text" data-param="args" placeholder="ex: --texto sales --com-cargo" />
          <div class="hint">Argumentos CLI diretos</div>
        </div>`;

        card.innerHTML = `
          <div class="card-hd">
            <span class="card-title">${{s.name}}</span>
            <a href="/v1/scripts/${{s.name}}/docs" style="font-size:12px;color:#818cf8;text-decoration:none">${{s.command}}</a>
          </div>
          <div class="card-body">
            <div class="ep"><span class="badge get">GET</span><span>/v1/scripts/${{s.name}}/run</span></div>
            <div class="ep"><span class="badge post">POST</span><span>/v1/scripts/${{s.name}}/run</span></div>
            <div class="params">${{fieldsHtml}}</div>
            <div class="actions">
              <button class="btn-primary" data-run="get">Executar GET</button>
              <button class="btn-sec" data-run="post">Executar POST</button>
              <button class="btn-sec" data-run="html">Abrir HTML</button>
              <button class="btn-sec" data-copy>Copiar curl</button>
            </div>
            <pre class="curl-box" data-curl></pre>
            <pre data-out style="display:none"></pre>
          </div>`;

        const buildUrl = () => {{
          const qs = new URLSearchParams();
          card.querySelectorAll('input[data-param]').forEach(inp => {{
            const val = inp.value.trim();
            if (val) qs.set(inp.dataset.param, val);
          }});
          const q = qs.toString();
          return `${{location.origin}}/v1/scripts/${{s.name}}/run${{q ? '?' + q : ''}}`;
        }};

        const updateCurl = () => {{
          card.querySelector('[data-curl]').textContent = `curl -s "${{buildUrl()}}"`;
        }};
        card.querySelectorAll('input').forEach(inp => inp.addEventListener('input', updateCurl));
        updateCurl();

        card.querySelector('[data-run="get"]').addEventListener('click', async () => {{
          const out = card.querySelector('[data-out]');
          out.style.display = 'block';
          out.textContent = 'Executando...';
          const r = await fetch(buildUrl());
          const data = await r.json();
          out.textContent = JSON.stringify(data, null, 2);
        }});

        card.querySelector('[data-run="post"]').addEventListener('click', async () => {{
          const out = card.querySelector('[data-out]');
          out.style.display = 'block';
          out.textContent = 'Executando...';
          const parts = [];
          card.querySelectorAll('input[data-param]').forEach(inp => {{
            const k = inp.dataset.param;
            const v = inp.value.trim();
            if (!v) return;
            if (k === 'args') parts.push(v);
            else if (v === 'true') parts.push(`--${{k}}`);
            else parts.push(`--${{k}} "${{v}}"`);
          }});
          const r = await fetch(`/v1/scripts/${{s.name}}/run`, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ args: parts.join(' ') }}),
          }});
          const data = await r.json();
          out.textContent = JSON.stringify(data, null, 2);
        }});

        card.querySelector('[data-run="html"]').addEventListener('click', () => {{
          const url = buildUrl();
          const sep = url.includes('?') ? '&' : '?';
          window.open(`${{url}}${{sep}}format=html`, '_blank');
        }});

        card.querySelector('[data-copy]').addEventListener('click', () => {{
          navigator.clipboard?.writeText(card.querySelector('[data-curl]').textContent);
        }});

        app.appendChild(card);
      }}
    }}
    load();
  </script>
</body>
</html>"""


@router.get("/v1/scripts/docs", include_in_schema=False)
async def scripts_swagger_docs():
    """Self-contained interactive API docs page for customizable scripts (no external CDN)."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=_render_scripts_docs_html())


@router.get("/v1/scripts/{name}/docs", include_in_schema=False)
async def single_script_docs(name: str):
    """Self-contained interactive API docs page for a single script."""
    from fastapi.responses import HTMLResponse

    clean = name.strip().lstrip("@/")
    if not _is_valid_script_name(clean) or not (_scripts_dir() / f"{clean}.py").is_file():
        raise HTTPException(status_code=404, detail=f"Script '@{clean}' not found")
    return HTMLResponse(content=_render_scripts_docs_html(only_name=clean))


def _parse_script_stdout_to_data(stdout: str) -> Any:
    """Parse script stdout into structured JSON data (parsed JSON or list of lines)."""
    import json

    stripped = (stdout or "").strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (list, dict)):
            return parsed
    except Exception:
        pass
    return [line.strip() for line in stripped.splitlines() if line.strip()]


def _format_script_api_response(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": res["name"],
        "exit_code": res["exit_code"],
        "data": _parse_script_stdout_to_data(res.get("stdout", "")),
        "stderr": res.get("stderr", ""),
    }


def _closeup_logo_data_uri() -> str:
    """Return the Close-UP logo as a base64 data URI when available."""
    import base64
    from pathlib import Path

    logo_path = Path(__file__).resolve().parents[3] / "assets" / "closeup_logo.png"
    if not logo_path.is_file():
        return ""
    encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _render_script_html_output(res: dict[str, Any]) -> str:
    """Render standardized HTML report for any script's JSON ``data`` output."""
    import html as _html
    from datetime import datetime

    payload = _format_script_api_response(res)
    name = _html.escape(str(payload["name"]))
    code = int(payload["exit_code"])
    stderr = _html.escape(str(payload.get("stderr") or ""))
    data = payload["data"]
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    rows: list[list[str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append([str(v) for v in item.values()])
            else:
                text = str(item)
                if " | " in text:
                    rows.append([part.strip() for part in text.split(" | ")])
                else:
                    rows.append([text])
    elif isinstance(data, dict):
        for k, v in data.items():
            rows.append([str(k), str(v)])

    max_cols = max((len(r) for r in rows), default=1)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        headers = [str(k) for k in data[0].keys()]
    elif max_cols == 2:
        headers = ["Nome", "Cargo / Detalhe"]
    elif max_cols > 2:
        headers = [f"Coluna {i + 1}" for i in range(max_cols)]
    else:
        headers = ["Resultado"]

    thead = "".join(f"<th>{_html.escape(h)}</th>" for h in ["#", *headers])
    tbody_parts = []
    for idx, r in enumerate(rows, start=1):
        padded = r + [""] * (max_cols - len(r))
        tds = "".join(f"<td>{_html.escape(c)}</td>" for c in padded)
        tbody_parts.append(f"<tr><td class='num'>{idx}</td>{tds}</tr>")
    tbody = "".join(tbody_parts) or (
        f"<tr><td colspan='{max_cols + 1}' class='empty'>Nenhum registro retornado.</td></tr>"
    )
    err_block = (
        f"<div class='err'><strong>stderr:</strong><pre>{stderr}</pre></div>"
        if stderr
        else ""
    )
    logo_html = """<svg class='logo' viewBox='0 0 210 56' xmlns='http://www.w3.org/2000/svg' aria-label='Close-UP'>
      <text x='4' y='38' font-family='Plus Jakarta Sans,system-ui,sans-serif' font-weight='800' font-style='italic' font-size='32' fill='#212129' letter-spacing='-1'>CLOSE</text>
      <rect x='4' y='44' width='96' height='3' rx='1.5' fill='#aa0012'/>
      <g transform='translate(152 28) rotate(-14)'>
        <ellipse cx='0' cy='0' rx='46' ry='22' fill='#aa0012'/>
        <text x='0' y='10' text-anchor='middle' font-family='Plus Jakarta Sans,system-ui,sans-serif' font-weight='800' font-style='italic' font-size='28' fill='#ffffff'>-UP</text>
      </g>
    </svg>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Relatório — {name}</title>
  <style>
    :root {{
      --cup-brand:#aa0012; --cup-brand-hover:#8a000f; --cup-brand-soft:#fff0f2; --cup-brand-on:#ffffff;
      --bg:#f8f8fa; --card:#ffffff; --surface-muted:#f3f3f6; --border:#dee0e5; --border-sub:#e8ebed;
      --text:#212129; --muted:#666b78; --ok-bg:#e8f7ed; --ok:#0a6b2e; --err-bg:#ffe8ed; --err:#ab0012;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); padding:28px 20px; }}
    .wrap {{ max-width:1040px; margin:0 auto; }}
    .header {{ background:var(--card); color:var(--text); border:1px solid var(--border); border-top:4px solid var(--cup-brand); border-radius:12px; padding:18px 22px; margin-bottom:16px; display:flex; flex-wrap:wrap; gap:14px; align-items:center; justify-content:space-between; box-shadow:0 1px 3px rgba(33,33,41,0.05); }}
    .brand-left {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; }}
    .logo {{ height:38px; width:auto; display:block; }}
    .title {{ font-size:18px; font-weight:700; margin:0 0 3px; color:var(--text); }}
    .title code {{ color:var(--cup-brand); background:var(--cup-brand-soft); padding:2px 8px; border-radius:6px; font-size:14px; }}
    .meta {{ font-size:12px; color:var(--muted); }}
    .badges {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .badge {{ padding:4px 10px; border-radius:999px; font-size:11px; font-weight:600; background:var(--surface-muted); color:var(--text); border:1px solid var(--border); }}
    .badge.ok {{ background:var(--ok-bg); color:var(--ok); border-color:transparent; }}
    .badge.fail {{ background:var(--err-bg); color:var(--err); border-color:transparent; }}
    .toolbar {{ display:flex; gap:10px; margin-bottom:14px; flex-wrap:wrap; }}
    .search {{ flex:1; min-width:220px; padding:9px 12px; border-radius:8px; border:1px solid var(--border); background:var(--card); color:var(--text); font-size:13px; }}
    .search:focus {{ outline:none; border-color:var(--cup-brand); }}
    .btn {{ padding:9px 14px; border-radius:8px; border:1px solid var(--border); background:var(--card); color:var(--text); font-size:12px; font-weight:600; cursor:pointer; }}
    .btn:hover {{ border-color:var(--cup-brand); color:var(--cup-brand); background:var(--cup-brand-soft); }}
    .btn-brand {{ background:var(--cup-brand); color:var(--cup-brand-on); border-color:var(--cup-brand); }}
    .btn-brand:hover {{ background:var(--cup-brand-hover); border-color:var(--cup-brand-hover); color:var(--cup-brand-on); }}
    .table-wrap {{ background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(33,33,41,0.04); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th {{ text-align:left; padding:11px 14px; background:var(--surface-muted); color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid var(--border); cursor:pointer; user-select:none; white-space:nowrap; }}
    th:hover {{ color:var(--cup-brand); background:var(--cup-brand-soft); }}
    th .sort-ind {{ margin-left:4px; font-size:10px; opacity:0.6; }}
    th.sorted .sort-ind {{ opacity:1; color:var(--cup-brand); }}
    td {{ padding:10px 14px; border-bottom:1px solid var(--border-sub); color:var(--text); }}
    tr:last-child td {{ border-bottom:none; }}
    tr:hover td {{ background:var(--cup-brand-soft); }}
    td.num {{ color:var(--muted); width:52px; font-variant-numeric:tabular-nums; }}
    td.empty {{ text-align:center; color:var(--muted); padding:28px; }}
    .err {{ margin-top:14px; padding:12px; border-radius:8px; border:1px solid var(--err); background:var(--err-bg); color:var(--err); font-size:12px; }}
    @media print {{ body {{ background:#fff; padding:0; }} .toolbar {{ display:none; }} .header,.table-wrap {{ box-shadow:none; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="brand-left">
        {logo_html}
        <div>
          <div class="title">Relatório — <code>@{name}</code></div>
          <div class="meta">Gerado em {generated_at} · Padrão Close-UP</div>
        </div>
      </div>
      <div class="badges">
        <span class="badge" id="count-badge">{len(rows)} registro(s)</span>
      </div>
    </div>
    <div class="toolbar">
      <input id="filter" class="search" type="text" placeholder="Filtrar resultados na tabela..." />
      <button class="btn btn-brand" onclick="exportPdf()">Exportar PDF</button>
      <button class="btn" onclick="exportHtml()">Exportar HTML</button>
      <button class="btn" onclick="exportEmail()">Enviar E-mail</button>
    </div>
    <div class="table-wrap">
      <table id="report-table">
        <thead><tr>{thead}</tr></thead>
        <tbody>{tbody}</tbody>
      </table>
    </div>
    {err_block}
  </div>
  <script>
    const SCRIPT_NAME = {repr(str(payload["name"]))};
    const inp = document.getElementById('filter');
    const tbody = document.querySelector('#report-table tbody');
    const badge = document.getElementById('count-badge');
    const ths = Array.from(document.querySelectorAll('#report-table thead th'));
    let sortCol = -1;
    let sortAsc = true;

    ths.forEach((th, idx) => {{
      const ind = document.createElement('span');
      ind.className = 'sort-ind';
      ind.textContent = '⇅';
      th.appendChild(ind);
      th.addEventListener('click', () => {{
        if (sortCol === idx) sortAsc = !sortAsc;
        else {{ sortCol = idx; sortAsc = true; }}
        ths.forEach((h, i) => {{
          h.classList.toggle('sorted', i === sortCol);
          h.querySelector('.sort-ind').textContent = i === sortCol ? (sortAsc ? '▲' : '▼') : '⇅';
        }});
        const trs = Array.from(tbody.querySelectorAll('tr'));
        trs.sort((a, b) => {{
          const av = (a.children[idx]?.textContent || '').trim();
          const bv = (b.children[idx]?.textContent || '').trim();
          const an = Number(av), bn = Number(bv);
          const cmp = (!Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== '')
            ? an - bn
            : av.localeCompare(bv, 'pt-BR', {{ sensitivity: 'base' }});
          return sortAsc ? cmp : -cmp;
        }});
        trs.forEach(tr => tbody.appendChild(tr));
      }});
    }});

    inp.addEventListener('input', () => {{
      const q = inp.value.trim().toLowerCase();
      let visible = 0;
      tbody.querySelectorAll('tr').forEach(tr => {{
        const show = !q || tr.textContent.toLowerCase().includes(q);
        tr.style.display = show ? '' : 'none';
        if (show) visible++;
      }});
      badge.textContent = visible + ' registro(s)';
    }});

    function exportPdf() {{
      window.print();
    }}

    function exportHtml() {{
      const clone = document.documentElement.cloneNode(true);
      const tb = clone.querySelector('.toolbar');
      if (tb) tb.remove();
      const html = '<!DOCTYPE html>\\n' + clone.outerHTML;
      const blob = new Blob([html], {{ type: 'text/html;charset=utf-8' }});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${{SCRIPT_NAME}}_relatorio.html`;
      a.click();
      URL.revokeObjectURL(a.href);
    }}

    async function exportEmail() {{
      const headers = Array.from(document.querySelectorAll('#report-table thead th')).map(th => th.textContent.trim());
      const visibleRows = [];
      tbody.querySelectorAll('tr').forEach(tr => {{
        if (tr.style.display === 'none') return;
        const cols = Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
        if (cols.length) visibleRows.push(cols);
      }});
      const esc = (s) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const thHtml = headers.map(h => `<th style="text-align:left;padding:9px 12px;background:#f3f3f6;color:#666b78;border:1px solid #dee0e5;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;">${{esc(h)}}</th>`).join('');
      const trHtml = visibleRows.map(r =>
        '<tr>' + r.map(c => `<td style="padding:9px 12px;border:1px solid #e8ebed;font-size:13px;color:#212129;">${{esc(c)}}</td>`).join('') + '</tr>'
      ).join('');
      const emailHtml = `
        <div style="font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#212129;border-top:4px solid #aa0012;padding-top:12px;">
          <h2 style="margin:0 0 6px;font-size:16px;color:#212129;">Relatório <span style="color:#aa0012;">@${{esc(SCRIPT_NAME)}}</span></h2>
          <p style="margin:0 0 12px;font-size:12px;color:#666b78;">${{visibleRows.length}} registro(s)</p>
          <table style="border-collapse:collapse;width:100%;max-width:800px;background:#ffffff;border:1px solid #dee0e5;">
            <thead><tr>${{thHtml}}</tr></thead>
            <tbody>${{trHtml}}</tbody>
          </table>
        </div>`.trim();
      const plainText = `Relatório @${{SCRIPT_NAME}}\\n\\n` + visibleRows.map(r => r.join(' | ')).join('\\n');

      try {{
        if (window.ClipboardItem && navigator.clipboard?.write) {{
          await navigator.clipboard.write([
            new ClipboardItem({{
              'text/html': new Blob([emailHtml], {{ type: 'text/html' }}),
              'text/plain': new Blob([plainText], {{ type: 'text/plain' }}),
            }}),
          ]);
        }} else {{
          await navigator.clipboard?.writeText(emailHtml);
        }}
      }} catch {{}}

      const btn = document.querySelector('[onclick="exportEmail()"]');
      if (btn) {{
        const orig = btn.textContent;
        btn.textContent = 'HTML copiado! Cole (Cmd+V) no e-mail';
        setTimeout(() => {{ btn.textContent = orig; }}, 4000);
      }}
      const subject = encodeURIComponent(`Relatório @${{SCRIPT_NAME}}`);
      window.location.href = `mailto:?subject=${{subject}}`;
    }}
  </script>
</body>
</html>"""


@router.post("/v1/scripts/run")
async def run_script_endpoint(request: Request):
    """Run a customizable Python script by name."""
    body = await request.json()
    name = str(body.get("name", "")).strip().lstrip("@/")
    args = str(body.get("args", ""))
    res = await asyncio.to_thread(_execute_custom_script, name, args)
    return _format_script_api_response(res)


@router.get("/v1/scripts/{name}/run")
async def run_named_script_get(name: str, request: Request):
    """Run a customizable Python script via GET (JSON by default, or HTML with ``?format=html``)."""
    import shlex
    from fastapi.responses import HTMLResponse

    clean_name = name.strip().lstrip("@/")
    params = dict(request.query_params)
    out_format = params.pop("format", "json").strip().lower()
    raw_args = params.pop("args", "")
    parts: list[str] = [raw_args] if raw_args.strip() else []
    for k, v in params.items():
        flag = k if k.startswith("--") else f"--{k.replace('_', '-')}"
        if v.lower() in ("true", "1", "yes"):
            parts.append(flag)
        elif v.lower() in ("false", "0", "no", ""):
            continue
        else:
            parts.append(f"{flag} {shlex.quote(v)}")
    res = await asyncio.to_thread(_execute_custom_script, clean_name, " ".join(parts))
    if out_format == "html":
        return HTMLResponse(content=_render_script_html_output(res))
    return _format_script_api_response(res)


@router.get("/v1/scripts/{name}/html", include_in_schema=False)
async def run_named_script_html(name: str, request: Request):
    """Convenience HTML report endpoint for a customizable Python script."""
    import shlex
    from fastapi.responses import HTMLResponse

    clean_name = name.strip().lstrip("@/")
    params = dict(request.query_params)
    params.pop("format", None)
    raw_args = params.pop("args", "")
    parts: list[str] = [raw_args] if raw_args.strip() else []
    for k, v in params.items():
        flag = k if k.startswith("--") else f"--{k.replace('_', '-')}"
        if v.lower() in ("true", "1", "yes"):
            parts.append(flag)
        elif v.lower() in ("false", "0", "no", ""):
            continue
        else:
            parts.append(f"{flag} {shlex.quote(v)}")
    res = await asyncio.to_thread(_execute_custom_script, clean_name, " ".join(parts))
    return HTMLResponse(content=_render_script_html_output(res))


@router.post("/v1/scripts/{name}/run")
async def run_named_script_post(name: str, request: Request):
    """Run a customizable Python script via POST with JSON ``{"args": "..."}``."""
    clean_name = name.strip().lstrip("@/")
    try:
        body = await request.json()
    except Exception:
        body = {}
    args = str(body.get("args", "")) if isinstance(body, dict) else ""
    res = await asyncio.to_thread(_execute_custom_script, clean_name, args)
    return _format_script_api_response(res)


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    slash_resp = await _maybe_handle_slash_script(request_body)
    if slash_resp is not None:
        return slash_resp

    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    model = request_body.model
    use_server_agent = (
        agent is not None
        and not request_body.tools
        and (not request_body.stream or bool(getattr(agent, "_tools", None)))
    )

    # Inject memory context into messages before dispatching
    config = getattr(request.app.state, "config", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            memory_service = getattr(request.app.state, "memory_service", None)
            facts = memory_service.list_facts() if memory_service is not None else []

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                # Direct engine paths need the server identity folded into
                # memory here so adapters receive one leading system message.
                # Agent paths build that same identity in BaseAgent; injecting
                # it at both layers duplicates the prompt around memory.
                if not use_server_agent:
                    messages = _ensure_identity_prompt(messages, config)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                enriched = inject_context(
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                    facts=facts,
                )
                connector_ctx = _build_connector_context(messages)
                if connector_ctx:
                    if enriched and enriched[0].role == Role.SYSTEM:
                        enriched[0] = replace(
                            enriched[0],
                            content=f"{enriched[0].text}\n\n{connector_ctx}".strip(),
                        )
                    else:
                        enriched.insert(
                            0,
                            Message(
                                role=Role.SYSTEM,
                                content=connector_ctx,
                                metadata={"memory_context": True},
                            ),
                        )
                # Rebuild after identity/context merging so downstream engine
                # adapters always receive exactly one system message.
                from openjarvis.server.models import ChatMessage

                new_msgs = []
                for msg in enriched:
                    new_msgs.append(
                        ChatMessage(
                            role=msg.role.value,
                            content=msg.content,
                            name=msg.name,
                            tool_calls=[
                                {
                                    "id": tool_call.id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.name,
                                        "arguments": tool_call.arguments,
                                    },
                                }
                                for tool_call in (msg.tool_calls or [])
                            ]
                            or None,
                            tool_call_id=getattr(msg, "tool_call_id", None),
                        )
                    )
                request_body.messages = new_msgs
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text_for_complexity = m.content
            break
    if query_text_for_complexity:
        try:
            from openjarvis.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    if request_body.stream:
        # When the client passes `tools`, stream the model's raw
        # OpenAI-compat function-calling decision directly from the engine
        # (bypassing the agent) — the streaming mirror of the non-streaming
        # #454 fix. Routing client-supplied tools through a server-side agent
        # would execute the agent's different tool set and drop the raw tool
        # call the caller expects (#414).
        #
        # Without client-supplied tools, keep streaming requests on the
        # configured server agent so its server-side tool loop is available
        # to the desktop UI and other stream:true clients (#735). Fall back to
        # direct token streaming when no tool-bearing agent is configured.
        if request_body.tools:
            return await _handle_stream_tools(
                engine,
                model,
                request_body,
                complexity_info,
                app_config=config,
                bus=getattr(request.app.state, "bus", None),
                memory_service=getattr(request.app.state, "memory_service", None),
            )
        if use_server_agent:
            return await _handle_agent_stream(
                agent,
                model,
                request_body,
                complexity_info,
                trace_store=getattr(request.app.state, "trace_store", None),
                bus=getattr(request.app.state, "bus", None),
                memory_service=getattr(request.app.state, "memory_service", None),
            )
        return await _handle_stream(
            engine,
            model,
            request_body,
            complexity_info,
            trace_store=getattr(request.app.state, "trace_store", None),
            app_config=config,
            bus=getattr(request.app.state, "bus", None),
            memory_service=getattr(request.app.state, "memory_service", None),
        )

    # Non-streaming: use agent if available, otherwise direct engine call.
    #
    # EXCEPTION: when the client explicitly passed `tools`, they're asking
    # for raw OpenAI-compat function-calling — return the model's
    # tool_call decision verbatim. Routing through `_handle_agent` would
    # call `agent.run(input_text)`, which IGNORES `request_body.tools`,
    # runs the agent's own internal tool loop with its own (different)
    # tool spec, and returns only `result.content` — so the model's
    # tool_calls vanish and the user sees a generic acknowledgement
    # (e.g. "Understood. If you have another request...") that the
    # agent's re-prompted LLM produced. See #414.
    #
    # If a future caller needs agent orchestration WITH client-supplied
    # tools (e.g. injecting MCP tools through this endpoint and wanting
    # the agent to execute them), add an explicit opt-in header rather
    # than removing this guard — silent re-routing is what produced #414.
    # ``_handle_agent`` (sync ``agent.run()``) and ``_handle_direct`` (sync
    # ``engine.generate()``) both make blocking upstream calls; run them in a
    # worker thread so a slow/wedged non-streaming request can't stall the
    # event loop and every other concurrent request with it.
    if use_server_agent:
        response = await asyncio.to_thread(
            _handle_agent,
            agent,
            model,
            request_body,
            complexity_info,
            trace_store=getattr(request.app.state, "trace_store", None),
            bus=getattr(request.app.state, "bus", None),
        )
    else:
        bus = getattr(request.app.state, "bus", None)
        response = await asyncio.to_thread(
            _handle_direct,
            engine,
            model,
            request_body,
            bus=bus,
            complexity_info=complexity_info,
            app_config=config,
        )

    # Hand the completed exchange to the background memory service.
    _remember_exchange(
        getattr(request.app.state, "memory_service", None),
        query_text_for_complexity,
        response,
        bus=getattr(request.app.state, "bus", None),
        source="server.chat",
    )
    return response


def _response_content(response) -> str:
    """Extract assistant text from an OpenAI-compatible response object."""
    content = ""
    choices = getattr(response, "choices", None)
    if choices:
        content = getattr(choices[0].message, "content", "") or ""
    return content


def _record_completed_exchange(
    memory_service,
    user_text: str,
    assistant_text: str,
    *,
    bus=None,
    source: str = "server.chat",
) -> None:
    """Publish or submit a completed exchange without blocking a reply."""
    if not user_text:
        return
    try:
        if bus is not None:
            from openjarvis.memory import publish_completed_exchange

            publish_completed_exchange(
                bus,
                user_text,
                assistant_text,
                source=source,
            )
        elif memory_service is not None:
            memory_service.submit(user_text, assistant_text)
    except Exception:  # noqa: BLE001 — memory is best-effort, never fail a reply
        logging.getLogger("openjarvis.server").debug(
            "Memory submit failed",
            exc_info=True,
        )


def _remember_exchange(
    memory_service,
    user_text: str,
    response,
    *,
    bus=None,
    source: str = "server.chat",
) -> None:
    """Record a completed non-streaming exchange."""
    _record_completed_exchange(
        memory_service,
        user_text,
        _response_content(response),
        bus=bus,
        source=source,
    )


def _engine_key_for_model(engine: Any, model: str) -> str | None:
    """Resolve the engine that advertised *model* through wrapper layers."""
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

    current = engine
    while current is not None:
        if isinstance(current, MultiEngine):
            return current.engine_key_for(model)
        if isinstance(current, InstrumentedEngine):
            current = current._inner
            continue
        if isinstance(current, GuardrailsEngine):
            current = current._engine
            continue
        engine_id = getattr(current, "engine_id", None)
        return engine_id if isinstance(engine_id, str) else None
    return None


def _local_engine_advertises(
    engine: Any, model: str, *, known_models: set[str] | None = None
) -> bool:
    """Whether a non-cloud engine behind *engine* lists *model* verbatim.

    Local OpenAI-compatible servers such as LM Studio advertise
    ``publisher/model`` IDs (e.g. ``qwen/qwen3-4b-2507``) that look like
    OpenRouter IDs to :func:`~openjarvis.server.cloud_router.is_cloud_model`.
    When a local engine lists the exact ID, it owns the model.
    """
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

    current = engine
    mapped_owner = False
    while True:
        if isinstance(current, InstrumentedEngine):
            current = current._inner
        elif isinstance(current, GuardrailsEngine):
            current = current._engine
        elif isinstance(current, MultiEngine):
            key = current.engine_key_for(model)
            current = next((eng for k, eng in current._engines if k == key), None)
            if current is None:
                return False
            mapped_owner = True
        else:
            break
    if getattr(current, "is_cloud", False) is True:
        return False
    if mapped_owner:
        return True
    if known_models is not None:
        return model in known_models
    try:
        return model in current.list_models()
    except Exception:
        logging.getLogger("openjarvis.server").debug(
            "Local model discovery failed; keeping ambiguous provider IDs local"
        )
        return "/" in model


def _uses_direct_cloud_router(engine: Any, model: str) -> bool:
    """Whether *model* should bypass the configured engine for direct cloud."""
    from openjarvis.server.cloud_router import get_provider, is_cloud_model

    if not is_cloud_model(model):
        return False
    engine_key = _engine_key_for_model(engine, model)
    if engine_key == "litellm":
        return False
    if engine_key == "nim":
        # Bare org/model IDs belong to the configured NIM backend. Explicit
        # cloud-provider namespaces and native cloud IDs retain their route.
        # Do not make a blocking model-list HTTP request on every chat turn.
        provider = get_provider(model)
        return "/" not in model or model.startswith(f"{provider}/")
    provider = get_provider(model)
    if model.startswith(f"{provider}/"):
        return True
    return not _local_engine_advertises(engine, model)


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
    app_config=None,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
        from openjarvis.telemetry.wrapper import instrumented_generate

        # `app.state.engine` may already be an InstrumentedEngine (the
        # common case when telemetry is wired in). If we then wrap it
        # with `instrumented_generate`, BOTH layers fire a
        # TELEMETRY_RECORD per call:
        #
        #   - InstrumentedEngine.generate() publishes a FULL record
        #     (energy_joules, GPU stats, token_counting_version, ...).
        #   - instrumented_generate() publishes a BARE record (timing +
        #     tokens only; no energy meter, no version stamp).
        #
        # The doubled count was the dominant driver of the bimodal
        # Wh/token distribution on the public leaderboard.
        #
        # The fix below is NOT "unwrap and call instrumented_generate":
        # that would have replaced "doubled records" with "every
        # request emits only a bare record with no energy / no version",
        # which the leaderboard's `current_methodology_only=True` filter
        # would then drop entirely. Instead, when the engine is already
        # an InstrumentedEngine, skip the wrapper and call `generate`
        # directly — InstrumentedEngine publishes the full per-record
        # event itself with energy + version intact. Only fall back to
        # the lightweight wrapper for engines that aren't already
        # instrumented.
        if isinstance(engine, InstrumentedEngine):
            result = engine.generate(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
        else:
            result = instrumented_generate(
                engine,
                messages,
                model=model,
                bus=bus,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


# _handle_agent runs on a worker thread (via asyncio.to_thread) for both
# the streaming and non-streaming routes, so concurrent requests against
# the same shared agent execute on real OS threads and can genuinely
# interleave. A lock per agent *instance* serializes the
# override-run-restore critical section below so one request's temporary
# `model` override can never be read as another's "original" value (#759).
# Key by object identity rather than by the agent itself: custom agents may be
# unhashable or may not support weak references.  The values are weak so this
# registry retains neither the agent nor an idle lock.  A caller keeps the lock
# alive from lookup through the full override/run/restore critical section.
_agent_model_locks: "weakref.WeakValueDictionary[int, threading.Lock]" = (
    weakref.WeakValueDictionary()
)
_agent_model_locks_guard = threading.Lock()


def _get_agent_model_lock(agent: Any) -> threading.Lock:
    """Return the lock serializing model overrides for *agent*, creating it
    on first use. One lock per agent instance, not global, so unrelated
    agents don't serialize against each other."""
    agent_id = id(agent)
    with _agent_model_locks_guard:
        lock = _agent_model_locks.get(agent_id)
        if lock is None:
            lock = threading.Lock()
            _agent_model_locks[agent_id] = lock
        return lock


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    bus=None,
) -> ChatCompletionResponse:
    """Run through agent.

    When *trace_store* is set, the agent run is wrapped in a
    ``TraceCollector`` (mirroring ``system/orchestrator.py``) so every
    completion records a ``Trace`` to ``traces.db``. Previously this endpoint
    called ``agent.run()`` raw, so the server never produced traces:
    ``traces.db`` stayed empty and spec_search's cold-start gate
    (``check_readiness``, min 20 traces) could never open.
    """
    from openjarvis.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one.
    # Locked for the full override-run-restore cycle (#759): only the
    # override/restore lines racing wouldn't be enough, since agent.run()
    # itself reads self._model throughout the call.
    with _get_agent_model_lock(agent):
        original_model = agent._model
        if model:
            agent._model = model
        try:
            if trace_store is not None:
                from openjarvis.traces.collector import TraceCollector

                collector = TraceCollector(agent, store=trace_store, bus=bus)
                result = collector.run(input_text, context=ctx)
            else:
                result = agent.run(input_text, context=ctx)
        finally:
            agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from openjarvis.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    bus=None,
    memory_service=None,
):
    """Run the configured agent and return its result as an SSE response.

    Agents own the tool-execution loop, which is synchronous today.  Run that
    loop in a worker thread and stream its final answer once complete.  This
    keeps ``stream:true`` clients (including the desktop UI) on the same agent
    and configured toolkit as non-streaming requests instead of bypassing the
    agent and silently dropping server-side tools.

    Requests that explicitly supply OpenAI ``tools`` continue to use
    ``_handle_stream_tools`` so their raw tool-call deltas are preserved.
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    query_text = ""
    for message in reversed(req.messages):
        if message.role == "user" and message.content:
            query_text = message.content
            break

    async def generate():
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            response = await asyncio.to_thread(
                _handle_agent,
                agent,
                model,
                req,
                complexity_info,
                trace_store=trace_store,
                bus=bus,
            )
        except Exception as exc:
            logging.getLogger("openjarvis.server").error(
                "Agent stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"Sorry, an error occurred: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        content = _response_content(response)
        if content:
            content_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[StreamChoice(delta=DeltaMessage(content=content))],
            )
            yield f"data: {content_chunk.model_dump_json()}\n\n"

        import json as _json

        finish_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(delta=DeltaMessage(), finish_reason="stop"),
            ],
        )
        finish_data = _json.loads(finish_chunk.model_dump_json())
        finish_data["usage"] = response.usage.model_dump()
        if complexity_info is not None:
            finish_data["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_data)}\n\n"

        _record_completed_exchange(
            memory_service,
            query_text,
            content,
            bus=bus,
            source="server.chat.stream",
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream_tools(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    app_config=None,
    bus=None,
    memory_service=None,
):
    """Stream a raw OpenAI-compat function-calling response via SSE.

    Used when the client passes `tools` together with `stream:true`.  Sources
    tool_calls from ``engine.stream_full()`` (which forwards the tools to the
    backend and parses tool_calls out of the streamed response) and emits them
    as SSE deltas, bypassing the agent entirely.  This is the streaming mirror
    of the non-streaming ``_handle_direct`` tool path.

    Engines without a tool-aware ``stream_full`` override fall back to the
    base-class default (content tokens + a ``stop`` finish_reason, no
    tool_calls) — identical to the prior plain-stream behaviour, so this never
    regresses non-tool-capable engines.
    """
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    use_cloud = await asyncio.to_thread(_uses_direct_cloud_router, engine, model)
    telemetry_engine = (
        "cloud" if use_cloud else (_engine_key_for_model(engine, model) or "ollama")
    )
    query_text = ""
    for _m in reversed(req.messages):
        if _m.role == "user" and _m.content:
            query_text = _m.content
            break

    async def generate():
        full_content = ""
        # Send the role chunk first (OpenAI convention).
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        finish_reason = "stop"
        try:
            async for sc in engine.stream_full(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                tools=req.tools,
            ):
                if sc.content:
                    full_content += sc.content
                    content_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[StreamChoice(delta=DeltaMessage(content=sc.content))],
                    )
                    yield f"data: {content_chunk.model_dump_json()}\n\n"
                if sc.tool_calls:
                    tc_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[
                            StreamChoice(delta=DeltaMessage(tool_calls=sc.tool_calls))
                        ],
                    )
                    yield f"data: {tc_chunk.model_dump_json()}\n\n"
                if sc.finish_reason:
                    finish_reason = sc.finish_reason
        except Exception as exc:
            import logging

            logging.getLogger("openjarvis.server").error(
                "Tool stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())
        # Tag the finish chunk with the engine label, matching _handle_stream
        # so UI/telemetry consumers see the same field on the tools path.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = telemetry_engine
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_dict)}\n\n"
        if full_content:
            _record_completed_exchange(
                memory_service,
                query_text,
                full_content,
                bus=bus,
                source="server.chat.stream",
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    app_config=None,
    bus=None,
    memory_service=None,
):
    """Stream response using SSE format.

    This no-agent fallback streams straight from the engine, bypassing the
    ``TraceCollector``. When *trace_store* is set we accumulate the streamed
    tokens and record a minimal ``Trace`` once the stream completes
    successfully.
    """
    import time

    from openjarvis.server.cloud_router import stream_cloud, stream_local

    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Last user message — recorded as the trace query.
    query_text = ""
    for _m in reversed(req.messages):
        if _m.role == "user" and _m.content:
            query_text = _m.content
            break

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = await asyncio.to_thread(_uses_direct_cloud_router, engine, model)
    telemetry_engine = (
        "cloud" if use_cloud else (_engine_key_for_model(engine, model) or "ollama")
    )

    async def generate():
        started_at = time.time()
        full_content = ""
        # Start with the configured route, then correct it below if the
        # MultiEngine safety path deliberately bypasses that route.
        actual_telemetry_engine = telemetry_engine
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from openjarvis.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    actual_telemetry_engine = "ollama"
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    token_iter = engine.stream(
                        messages,
                        model=model,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    )
            async for token in token_iter:
                full_content += token
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("openjarvis.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Record a trace for the completed stream (best-effort; never breaks
        # the response). Mirrors the agent path so streamed chats also
        # populate traces.db.
        if trace_store is not None and full_content:
            from openjarvis.traces.collector import record_response_trace

            record_response_trace(
                trace_store,
                query=query_text,
                result=full_content,
                model=model,
                engine=actual_telemetry_engine,
                started_at=started_at,
                ended_at=time.time(),
            )

        if full_content:
            _record_completed_exchange(
                memory_service,
                query_text,
                full_content,
                bus=bus,
                source="server.chat.stream",
            )

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the backend that actually yielded tokens,
        # including the explicit local fallback around a stale MultiEngine map.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = actual_telemetry_engine

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List selectable engine models for the installed-model picker.

    Direct cloud models live in the Cloud Models tab. Models advertised by a
    configured LiteLLM engine remain here because LiteLLM owns their routing
    and may use provider-qualified IDs that resemble OpenRouter IDs.
    """
    from openjarvis.server.cloud_router import (
        _load_keys,
        is_cloud_model,
        list_local_models,
    )

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out direct-cloud model IDs that may appear via MultiEngine, but
    # retain provider-qualified IDs owned by configured engines like LiteLLM or NIM.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = await asyncio.to_thread(engine.list_models)
    known_models = set(all_ids)
    model_ids = [
        m
        for m in all_ids
        if not is_cloud_model(m)
        or _engine_key_for_model(engine, m) in ("litellm", "nim")
        or _local_engine_advertises(engine, m, known_models=known_models)
    ]
    if not model_ids:
        model_ids = await list_local_models()

    # Include configured Azure deployments (or default Azure models) first so
    # they appear at the top of the picker when Azure is configured.
    cloud_keys = _load_keys()
    if cloud_keys.get("AZURE_OPENAI_API_KEY") and cloud_keys.get("AZURE_OPENAI_ENDPOINT"):
        azure_deps = [
            dep.strip()
            for dep in cloud_keys.get("AZURE_OPENAI_DEPLOYMENT", "").split(",")
            if dep.strip()
        ]
        if not azure_deps:
            azure_deps = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3-mini"]
        azure_ids = [f"azure/{dep_name}" for dep_name in azure_deps]
        model_ids = azure_ids + [m for m in model_ids if m not in azure_ids]

    # Keep embed-only models out of the chat model picker. They still work for
    # memory/retrieval via the embedder path; putting them in /v1/models made
    # the UI auto-select nomic-embed-text and fail every generation with 400.
    model_ids = [m for m in model_ids if not is_embed_only_model(m)]

    return ModelListResponse(
        data=[
            ModelObject(
                id=mid,
                owned_by=(
                    _engine_key_for_model(engine, mid)
                    if _engine_key_for_model(engine, mid) in ("litellm", "nim")
                    else "openjarvis"
                ),
            )
            for mid in model_ids
        ],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    try:
        async with _httpx.AsyncClient(base_url=host, timeout=600.0) as client:
            resp = await client.post(
                "/api/pull",
                json={"name": model_name, "stream": False},
            )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    try:
        async with _httpx.AsyncClient(base_url=host, timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                "/api/delete",
                json={"name": model_name},
            )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )

    return {"status": "deleted", "model": model_name}


_ALLOWED_CLOUD_CONFIG_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "ATLASCLOUD_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_VERSION",
    }
)


def _is_allowed_cloud_key(name: str) -> bool:
    return name.endswith("_API_KEY") or name in _ALLOWED_CLOUD_CONFIG_KEYS


def _write_cloud_keys_env(updates: dict[str, str]) -> None:
    """Persist cloud key updates to ~/.openjarvis/cloud-keys.env (0600)."""
    from openjarvis.core.paths import get_config_dir

    keys_path = get_config_dir() / "cloud-keys.env"
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if keys_path.exists():
        for raw_line in keys_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    for k, v in updates.items():
        if v:
            existing[k] = v
        else:
            existing.pop(k, None)
    lines = [f"{k}={v}" for k, v in existing.items()]
    keys_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    with contextlib.suppress(OSError):
        keys_path.chmod(0o600)


@router.get("/v1/cloud/status")
async def get_cloud_status():
    """Return boolean status of configured cloud keys and Azure deployments."""
    from openjarvis.server.cloud_router import _load_keys

    keys = _load_keys()
    status = {k: bool(keys.get(k)) for k in _ALLOWED_CLOUD_CONFIG_KEYS}
    deployments = [
        d.strip()
        for d in keys.get("AZURE_OPENAI_DEPLOYMENT", "").split(",")
        if d.strip()
    ]
    return {
        "keys": status,
        "azure_deployments": deployments,
        "azure_endpoint": keys.get("AZURE_OPENAI_ENDPOINT", ""),
        "azure_api_version": keys.get("AZURE_OPENAI_API_VERSION", ""),
    }


@router.post("/v1/cloud/keys")
async def save_cloud_keys_endpoint(request: Request):
    """Save cloud keys/config to cloud-keys.env and hot-reload CloudEngine."""
    body = await request.json()
    raw_keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(raw_keys, dict):
        raise HTTPException(status_code=400, detail="'keys' object is required")
    updates = {
        str(k): str(v).strip()
        for k, v in raw_keys.items()
        if _is_allowed_cloud_key(str(k))
    }
    _write_cloud_keys_env(updates)
    return await reload_cloud_engine(request)


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os

    submitted_keys: dict[str, str] | None = None
    try:
        body = await request.json()
        raw_keys = body.get("keys") if isinstance(body, dict) else None
        if isinstance(raw_keys, dict):
            submitted_keys = {
                str(k): str(v)
                for k, v in raw_keys.items()
                if _is_allowed_cloud_key(str(k))
            }
    except Exception:
        submitted_keys = None

    if submitted_keys is not None:
        for key, value in submitted_keys.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    else:
        # Compatibility fallback for non-desktop/manual configurations.
        keys_path = get_config_dir() / "cloud-keys.env"
        if keys_path.exists():
            for raw_line in keys_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip()
                    if (val.startswith('"') and val.endswith('"')) or (
                        val.startswith("'") and val.endswith("'")
                    ):
                        if len(val) >= 2:
                            val = val[1:-1]
                    os.environ[k.strip()] = val

    # Try to build a fresh CloudEngine.
    try:
        from openjarvis.engine.cloud import CloudEngine
        from openjarvis.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
            agent = getattr(request.app.state, "agent", None)
            if agent is not None and hasattr(agent, "_engine"):
                agent._engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.server.savings import compute_savings, savings_to_dict
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        # current_methodology_only excludes pre-fix legacy rows from
        # the leaderboard's per-token efficiency numerator/denominator
        # — see the comment on _time_filter for the bimodal-Wh/token
        # background.
        summary = agg.summary(since=session_start, current_methodology_only=True)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from openjarvis.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = await asyncio.to_thread(scanner.run_all)
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]
