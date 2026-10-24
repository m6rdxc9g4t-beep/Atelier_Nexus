"""Claude par l'abonnement : le programme `claude` (Claude Code) en mode non interactif.

Pour qui a un forfait Claude (Pro, Max…) sans clé API : Nexus appelle `claude -p`, comme
Atelier Viz et Atelier Savoir. La consommation compte dans les limites de l'abonnement, et
aucune clé n'est nécessaire (connexion faite une fois avec `claude` dans un terminal).

Le mode non interactif n'a pas d'appels d'outils « natifs » utilisables ici : chaque tour
renvoie un objet JSON validé par schéma (`--json-schema`) — soit un texte final, soit des
appels d'outils. Nexus exécute lui-même les outils (validations et verrou local compris) et
renvoie leurs résultats au tour suivant, dans la conversation transmise sur l'entrée standard.
Le provider garde donc le contrat commun (`ToolUseBlock` / `ToolResultBlock`) : la boucle
d'agent ne voit pas la différence avec l'API.

Précautions (identiques à Savoir) : ANTHROPIC_API_KEY / AUTH_TOKEN / BASE_URL retirées de
l'environnement (sinon la clé serait facturée à l'usage), aucun outil de Claude Code
(`--tools ""`), pas de MCP ni de commandes, pas de session conservée, dossier de travail vide.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from app.core.llm.errors import ProviderRequestError, ProviderUnavailableError
from app.core.llm.providers.base import LLMProvider
from app.core.llm.types import (
    AttachmentBlock,
    ContentBlock,
    ImageBlock,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    Message,
    ResponseComplete,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)
from app.core.processes import (
    CLAUDE_WINDOWS_VARS,
    NO_WINDOW,
    is_batch,
    kill_tree,
    pick_environment,
    windows_command,
)

CLI_MODELS = ["sonnet", "opus", "haiku"]
#: Environnement de la CLI en liste blanche (SUITE.md §5.3 ; Windows : §9.6). Rien d'autre : ni
#: ANTHROPIC_* (la clé serait facturée à l'usage), ni secret ou réglage de Nexus.
CLI_ENV = (
    "HOME",
    "USER",
    "LOGNAME",
    "PATH",
    "SHELL",
    "LANG",
    "TMPDIR",
    "TZ",
    "CLAUDE_CONFIG_DIR",
)
MAX_RESULT_CHARS = 40_000
INSTRUCTION = (
    "Poursuis la conversation fournie sur l'entrée standard : réponds à son dernier message par "
    "un seul appel à StructuredOutput (format JSON demandé ; les actions d'Atelier Nexus se "
    "nomment dans tool_calls, jamais en appel direct)."
)
INCOMPLETE = "réponse incomplète de Claude Code (aucun résultat final) ; réessayez"
NOT_LOGGED_IN = (
    "Claude Code n'est pas connecté : ouvrez le Terminal, tapez « claude » et connectez-vous "
    "avec votre compte Claude, puis réessayez."
)


def find_claude_binary(configured: str | None = None) -> str | None:
    """Emplacements usuels de Claude Code (une app lancée du Finder a un PATH minimal ;
    Windows : installation native `claude.exe`, ou `claude.cmd` de `npm install -g`)."""
    home = Path.home()
    windows: list[str] = []
    if sys.platform == "win32":
        windows.append(str(home / ".local" / "bin" / "claude.exe"))
        appdata = os.environ.get("APPDATA")
        if appdata:
            windows.append(str(Path(appdata) / "npm" / "claude.cmd"))
    candidates = [
        configured,
        os.environ.get("CLAUDE_PATH"),
        shutil.which("claude", path=_search_path()),
        *windows,
        str(home / ".local" / "bin" / "claude"),
        str(home / ".claude" / "local" / "claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        str(home / ".npm-global" / "bin" / "claude"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def subscription_env(binary: str | None = None) -> dict[str, str]:
    """Environnement de la CLI : liste blanche (§5.3, + variables système de Windows §9.6),
    dossier de l'exécutable en tête du PATH, trafic non essentiel coupé."""
    names = [*CLI_ENV, *(CLAUDE_WINDOWS_VARS if sys.platform == "win32" else ())]
    env = pick_environment(os.environ, names)
    current = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    env = {k: v for k, v in env.items() if k.upper() != "PATH"}
    home = Path.home()
    extra = [str(home / ".local" / "bin")]
    if sys.platform != "win32":
        extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    if binary:
        extra.insert(0, str(Path(binary).parent))
    env["PATH"] = os.pathsep.join(p for p in [*extra, current] if p)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def _search_path() -> str:
    """PATH sans entrée relative ni dossier `node_modules/.bin` (§5.3)."""
    entries = os.environ.get("PATH", "").split(os.pathsep)
    kept = [
        e for e in entries if os.path.isabs(e) and Path(e).parts[-2:] != ("node_modules", ".bin")
    ]
    return os.pathsep.join(kept)


# ─── Conversation → texte, réponse → blocs ────────────────────────


def response_schema(tools: Sequence[ToolSpec]) -> dict[str, Any]:
    text = {"type": "string", "description": "Texte pour l'utilisateur (Markdown)."}
    if not tools:
        return {"type": "object", "properties": {"text": text}, "required": ["text"]}
    return {
        "type": "object",
        "properties": {
            "text": text,
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [t.name for t in tools]},
                        "arguments": {
                            "type": "string",
                            "description": "Arguments de l'outil : objet JSON sérialisé.",
                        },
                    },
                    "required": ["name", "arguments"],
                },
            },
        },
        "required": ["text", "tool_calls"],
    }


def system_prompt(request: LLMRequest) -> str:
    parts = [request.system or "Tu es un assistant utile."]
    if request.tools:
        lines = [
            "",
            "# Actions d'Atelier Nexus",
            "Les actions ci-dessous ne sont PAS des outils de cette session : ton seul outil est "
            "`StructuredOutput`, et un appel direct à une action échoue (« No such tool "
            "available »). Pour utiliser une action, NOMME-LA dans `tool_calls` de l'objet que tu "
            "passes à `StructuredOutput` : Atelier Nexus l'exécute lui-même et te renvoie son "
            "résultat dans la conversation, au tour suivant.",
        ]
        for tool in request.tools:
            schema = json.dumps(tool.input_schema, ensure_ascii=False, separators=(",", ":"))
            lines.append(
                f"- `{tool.name}` : {tool.description}\n  Arguments (JSON Schema) : {schema}"
            )
        lines += [
            "",
            "# Format de réponse (obligatoire)",
            "Réponds UNIQUEMENT par l'objet JSON du schéma imposé, en un seul appel à "
            "`StructuredOutput` et rien d'autre :",
            '- pour utiliser des actions : `tool_calls` = [{"name": …, "arguments": "{…JSON…}"}] '
            "(plusieurs à la fois si elles sont indépendantes) ; `text` peut annoncer en une phrase "
            "ce que tu fais ;",
            "- pour répondre à l'utilisateur : `tool_calls` = [] et `text` = ta réponse finale "
            "COMPLÈTE (tout ce que l'utilisateur doit lire : rien n'est transmis hors de l'objet).",
            "N'invente jamais le résultat d'un outil : attends-le. Une action soumise à validation "
            "peut être refusée par l'utilisateur : tiens-en compte.",
        ]
        parts.append("\n".join(lines))
    return "\n".join(parts)


def transcript_parts(messages: Sequence[Message]) -> list[str | ImageBlock]:
    """La conversation en sections de texte, images à leur place (pour l'entrée stream-json)."""
    out: list[str | ImageBlock] = []
    for message in messages:
        for block in message.content:
            if isinstance(block, ImageBlock):
                out.append(block)
            elif isinstance(block, AttachmentBlock):
                out.append(f"## Utilisateur\n[Pièce jointe « {block.name} » non chargée.]")
            elif isinstance(block, TextBlock) and block.text.strip():
                who = "Utilisateur" if message.role == "user" else "Assistant"
                out.append(f"## {who}\n{block.text.strip()}")
            elif isinstance(block, ToolUseBlock):
                args = json.dumps(block.input, ensure_ascii=False)
                out.append(
                    f"## Assistant → appel de l'outil `{block.name}` (id {block.id})\n{args}"
                )
            elif isinstance(block, ToolResultBlock):
                content = block.content
                if len(content) > MAX_RESULT_CHARS:
                    content = content[:MAX_RESULT_CHARS] + "\n[… résultat tronqué]"
                flag = " — ERREUR" if block.is_error else ""
                out.append(
                    f"## Résultat de `{block.tool_name}` (id {block.tool_use_id}){flag}\n{content}"
                )
    return out


def transcript(messages: Sequence[Message]) -> str:
    return "\n\n".join(p for p in transcript_parts(messages) if isinstance(p, str))


def stream_json_input(messages: Sequence[Message]) -> str:
    """Conversation avec images : un message utilisateur au format stream-json de Claude Code
    (sections de texte et images dans l'ordre)."""
    content: list[dict[str, Any]] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            content.append({"type": "text", "text": "\n\n".join(pending)})
            pending.clear()

    for part in transcript_parts(messages):
        if isinstance(part, ImageBlock):
            flush()
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": part.media_type, "data": part.data},
                }
            )
        else:
            pending.append(part)
    flush()
    line = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(line, ensure_ascii=False) + "\n"


def result_line(stdout: str) -> str:
    """Sortie stream-json : la dernière ligne `result` (même forme que --output-format json)."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "result":
            return line
    return ""


STRUCTURED_TOOL = "StructuredOutput"


def loose_text(stdout: str) -> str:
    """Texte écrit par le modèle HORS de l'objet structuré (sortie stream-json).

    Claude Code laisse parfois le modèle écrire sa réponse en texte libre avant l'appel à
    `StructuredOutput`, puis mettre dans l'objet une phrase de conclusion seulement : sans ce
    texte, la réponse était perdue (« Je n'ai rien écrit pour l'instant. »).

    Seuls comptent les messages qui précèdent le dernier appel à `StructuredOutput` ; un message
    qui tente un autre outil (appel direct refusé, « No such tool available ») est ignoré avec
    son texte : c'est une narration de cette tentative, pas une réponse à l'utilisateur."""
    messages: list[tuple[list[str], set[str]]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        texts: list[str] = []
        tools: set[str] = set()
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and str(block.get("text") or "").strip():
                texts.append(str(block["text"]).strip())
            elif block.get("type") == "tool_use":
                tools.add(str(block.get("name")))
        messages.append((texts, tools))
    last = max((i for i, (_, tools) in enumerate(messages) if STRUCTURED_TOOL in tools), default=-1)
    kept = [
        text
        for texts, tools in messages[: last + 1]
        if not (tools - {STRUCTURED_TOOL})
        for text in texts
    ]
    return "\n\n".join(kept)


def _last_line(text: str) -> str:
    """Dernière ligne non vide, bornée (message d'erreur lisible)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:400] if lines else ""


def _flat(text: str) -> str:
    return " ".join(text.split())


def merge_text(loose: str, structured: str) -> str:
    """Réponse pour l'utilisateur : le texte de l'objet, complété du texte libre qu'il ne
    reprend pas (jamais en double)."""
    a, b = _flat(loose), _flat(structured)
    if not a or a in b:
        return structured
    if not b or b in a:
        return loose
    return f"{loose}\n\n{structured}"


def parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except ValueError:
            return {"_arguments_invalides": raw[:500]}
        return value if isinstance(value, dict) else {"_arguments_invalides": raw[:500]}
    return {}


def to_response(structured: dict[str, Any], model: str, usage: Usage) -> LLMResponse:
    content: list[ContentBlock] = []
    text = str(structured.get("text") or "").strip()
    if text:
        content.append(TextBlock(text=text))
    for call in structured.get("tool_calls") or []:
        if not isinstance(call, dict) or not call.get("name"):
            continue
        content.append(
            ToolUseBlock(
                id=f"cli_{uuid.uuid4().hex[:12]}",
                name=str(call["name"]),
                input=parse_arguments(call.get("arguments", call.get("input"))),
            )
        )
    if not content:
        content.append(TextBlock(text="(réponse vide)"))
    calls = any(isinstance(b, ToolUseBlock) for b in content)
    return LLMResponse(
        provider="anthropic",
        model=model,
        content=content,
        stop_reason="tool_use" if calls else "end_turn",
        usage=usage,
    )


def usage_of(payload: dict[str, Any]) -> Usage:
    u = payload.get("usage") or {}
    if not isinstance(u, dict):
        return Usage()
    total_in = sum(
        int(u.get(k) or 0)
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    return Usage(input_tokens=total_in, output_tokens=int(u.get("output_tokens") or 0))


# ─── Provider ─────────────────────────────────────────────────────


class ClaudeCodeProvider(LLMProvider):
    """Claude via `claude -p` et l'abonnement de l'utilisateur (nom de provider : anthropic)."""

    name = "anthropic"

    def __init__(
        self, *, binary: str | None, default_model: str = "sonnet", timeout: float = 300.0
    ) -> None:
        super().__init__(default_model)
        self.binary = binary
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return self.binary is not None

    async def _exec(
        self, args: list[str], stdin: str | None, timeout: float
    ) -> tuple[int, str, str]:
        if self.binary is None:
            raise ProviderRequestError(
                "Claude Code est introuvable : installez-le (https://claude.com/claude-code), puis "
                "lancez « claude » une fois dans un terminal pour vous connecter.",
                provider=self.name,
            )
        # Windows : `claude.cmd` (npm) passerait les arguments (prompt système, schéma) par
        # cmd.exe, qui les réinterprète : lancé par node.exe directement, sinon refusé
        command = windows_command([self.binary, *args])
        if sys.platform == "win32" and is_batch(command[0]):
            raise ProviderUnavailableError(
                "Claude Code est installé par un script .cmd que Nexus ne lance pas (ses "
                "arguments seraient réinterprétés par cmd.exe) : installez la version native "
                "(https://claude.com/claude-code) ou indiquez son chemin (CLAUDE_CLI_PATH).",
                provider=self.name,
            )
        with tempfile.TemporaryDirectory(prefix="nexus-claude-") as workdir:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=subscription_env(command[0]),
                    cwd=workdir,
                    creationflags=NO_WINDOW,
                )
            except OSError as exc:
                raise ProviderUnavailableError(
                    f"Impossible de lancer Claude Code : {exc}", provider=self.name
                ) from exc
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout
                )
            except TimeoutError as exc:
                kill_tree(proc.pid)
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
                raise ProviderUnavailableError(
                    f"Claude n'a pas répondu en {timeout:g} s.", provider=self.name
                ) from exc
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.resolve_model(request)
        args = [
            "-p", INSTRUCTION,
            # stream-json : la seule sortie qui montre aussi le texte écrit hors de l'objet
            "--output-format", "stream-json", "--verbose",
            "--json-schema", json.dumps(response_schema(request.tools), ensure_ascii=False),
            "--system-prompt", system_prompt(request),
            "--model", model,
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]  # fmt: skip
        if any(isinstance(b, ImageBlock) for m in request.messages for b in m.content):
            # Images : entrée stream-json (le texte simple ne peut pas les porter)
            args[1 + args.index("--verbose") : 1 + args.index("--verbose")] = [
                "--input-format", "stream-json",
            ]  # fmt: skip
            code, stdout, stderr = await self._exec(
                args, stream_json_input(request.messages), self.timeout
            )
        else:
            code, stdout, stderr = await self._exec(
                args, transcript(request.messages), self.timeout
            )
        return self._extract(code, stdout, stderr, model)

    def _extract(self, code: int, stdout: str, stderr: str, model: str) -> LLMResponse:
        line = result_line(stdout)
        try:
            payload = json.loads(line) if line else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            # Pas de ligne `result` (flux tronqué, processus interrompu) : jamais le flux brut
            # dans le message (identifiants de session, chemins) ; stderr seulement, borné
            raise self._error(_last_line(stderr) or INCOMPLETE)
        if payload.get("is_error") or code != 0:
            raise self._error(str(payload.get("result") or stderr or "erreur inconnue").strip())
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            loose = loose_text(stdout)
            if loose:
                structured = {
                    **structured,
                    "text": merge_text(loose, str(structured.get("text") or "")),
                }
        else:
            # Sortie non structurée (ancienne version) : texte brut, ou JSON dans `result`. Le
            # texte libre n'est pas ajouté : il répète ce même JSON
            result = str(payload.get("result") or "")
            try:
                parsed = json.loads(result)
                structured = parsed if isinstance(parsed, dict) else {"text": result}
            except ValueError:
                structured = {"text": result}
        return to_response(structured, model, usage_of(payload))

    def _error(self, detail: str) -> Exception:
        lowered = detail.lower()
        if (
            "login" in lowered
            or "log in" in lowered
            or "authenticat" in lowered
            or "not logged" in lowered
        ):
            return ProviderRequestError(NOT_LOGGED_IN, provider=self.name)
        if "limit" in lowered or "quota" in lowered or "overloaded" in lowered:
            # Transitoire : permet le repli vers Ollama s'il est configuré
            return ProviderUnavailableError(
                "Limite d'utilisation de votre abonnement Claude atteinte (ou service saturé) : "
                "réessayez plus tard, ou utilisez Ollama en attendant.",
                provider=self.name,
            )
        return ProviderRequestError(
            f"Claude Code a renvoyé une erreur : {detail[:400]}", provider=self.name
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        # Réponse structurée : pas de texte partiel exploitable, on émet la réponse d'un bloc
        response = await self.complete(request)
        if response.text:
            yield TextDelta(text=response.text)
        yield ResponseComplete(response=response)

    async def list_models(self) -> list[str]:
        code, stdout, _ = await self._exec(["auth", "status"], None, 20)
        try:
            info = json.loads(stdout or "{}")
        except ValueError:
            info = {}
        logged_in = info.get("loggedIn", code == 0) if isinstance(info, dict) else code == 0
        if not logged_in:
            raise ProviderUnavailableError(NOT_LOGGED_IN, provider=self.name)
        return list(CLI_MODELS)
