"""Réglages modifiables depuis l'interface : lecture et écriture du fichier `.env`.

Le `.env` lu par `Settings` est celui du dossier courant : `backend/.env` en développement,
`~/Library/Application Support/Atelier Nexus/.env` (Windows : `%APPDATA%\Atelier Nexus\.env`)
dans l'application de bureau.

- Seules les clés de `FIELDS` sont modifiables (liste blanche). Les commandes exécutées
  (`TAB_MCP_COMMAND`) et les chemins techniques restent hors de l'interface.
- Les secrets ne sont jamais renvoyés : seulement « configuré » et les 4 derniers caractères.
- Écriture qui préserve commentaires et ordre, atomique, droits 600.
- Une variable d'environnement du processus l'emporte sur le `.env` : signalé (`source`).
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.config import Settings

Kind = Literal["text", "url", "secret", "choice", "path"]
Group = Literal[
    "Validation des actions", "Modèles", "Applications Atelier", "Atelier Cuisine", "GitHub"
]


@dataclass(frozen=True)
class EditableField:
    key: str
    label: str
    group: Group
    kind: Kind
    help: str = ""
    choices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def attr(self) -> str:
        return self.key.lower()


FIELDS: tuple[EditableField, ...] = (
    EditableField("APPROVAL_MODE", "Actions à valider", "Validation des actions", "choice",
                  "Chaque action : toute action d'un agent ou d'une étape de workflow, lectures comprises, "
                  "attend « Autoriser ». Seulement les écritures : les lectures s'exécutent seules.",
                  ("every_step", "writes_only")),
    EditableField("CLAUDE_MODE", "Accès à Claude", "Modèles", "choice",
                  "Abonnement : le programme claude (Claude Code) de cet ordinateur, connecté à votre compte. "
                  "Automatique : la clé API si elle est renseignée, sinon l'abonnement.", ("auto", "cli", "api")),
    EditableField("CLAUDE_CLI_MODEL", "Modèle Claude (abonnement)", "Modèles", "choice", "", ("sonnet", "opus", "haiku")),
    EditableField("ANTHROPIC_API_KEY", "Clé API Claude", "Modèles", "secret",
                  "Seulement sans abonnement : console.anthropic.com → API Keys (facturé à l'usage)."),
    EditableField("ANTHROPIC_MODEL", "Modèle Claude (clé API)", "Modèles", "text"),
    EditableField("OLLAMA_BASE_URL", "Adresse d'Ollama", "Modèles", "url"),
    EditableField("OLLAMA_MODEL", "Modèle local (Ollama)", "Modèles", "text",
                  "Doit être installé : ollama pull <modèle>."),
    EditableField("LLM_DEFAULT_PROVIDER", "Moteur par défaut", "Modèles", "choice",
                  "Les agents « 100 % local » utilisent toujours Ollama.", ("anthropic", "ollama")),
    EditableField("LLM_FALLBACK_PROVIDER", "Moteur de secours", "Modèles", "choice",
                  "Utilisé si le moteur demandé est momentanément indisponible.", ("", "anthropic", "ollama")),
    EditableField("DATA_VIA_BASE_URL", "Atelier Viz (Data Via)", "Applications Atelier", "url"),
    EditableField("PROJETS_BASE_URL", "Atelier Projets", "Applications Atelier", "url"),
    EditableField("PROJETS_IMPORT_TOKEN", "Jeton d'import Atelier Projets", "Applications Atelier", "secret",
                  "Seulement si Projets définit ATELIER_IMPORT_TOKEN."),
    EditableField("TRESORERIE_BASE_URL", "Atelier Trésorerie", "Applications Atelier", "url"),
    EditableField("CINE_BASE_URL", "Atelier Ciné", "Applications Atelier", "url",
                  "Mode serveur : port 4000 ; app Mac : 47321."),
    EditableField("WIKI_BASE_URL", "Atelier Wiki", "Applications Atelier", "url",
                  "API d'Atelier Wiki (port 3200 par défaut)."),
    EditableField("FORMULAIRE_BASE_URL", "Atelier Formulaire", "Applications Atelier", "url",
                  "API d'Atelier Formulaire (port 3300 par défaut)."),
    EditableField("CONVERT_BASE_URL", "Atelier Convert", "Applications Atelier", "url",
                  "API d'Atelier Convert (port 8010 par défaut) : workflows et extension Agent_DatAnalyst."),
    EditableField("SAVOIR_BASE_URL", "Atelier Savoir", "Applications Atelier", "url",
                  "Lancez Savoir avec ATELIER_PORT=5051 (5050 est pris par Trésorerie)."),
    EditableField("TAB_EXPORTS_DIR", "Instantanés d'Atelier Tab", "Applications Atelier", "path",
                  "Dossier exports de Tab (par défaut ~/Atelier_Tab/exports)."),
    EditableField("CUISINE_SUPABASE_URL", "Adresse du projet Supabase", "Atelier Cuisine", "url",
                  "App en ligne. Supabase → Project Settings → API → Project URL (https://<projet>.supabase.co)."),
    EditableField("CUISINE_SUPABASE_ANON_KEY", "Clé publique (anon)", "Atelier Cuisine", "secret",
                  "Clé « publishable » (sb_publishable_…) ou « anon » de l'app. Jamais la clé service_role "
                  "ou secrète : elle est refusée."),
    EditableField("CUISINE_EMAIL", "E-mail du foyer", "Atelier Cuisine", "text",
                  "Le compte avec lequel vous vous connectez à Atelier Cuisine."),
    EditableField("CUISINE_PASSWORD", "Mot de passe du foyer", "Atelier Cuisine", "secret",
                  "Lecture seule : Nexus ne voit que les données de ce compte (règles RLS de Supabase)."),
    EditableField("CUISINE_REFRESH_TOKEN", "Ou jeton de rafraîchissement", "Atelier Cuisine", "secret",
                  "À la place du mot de passe : renouvelé automatiquement ensuite (cuisine-session.json)."),
    EditableField("GITHUB_TOKEN", "Jeton GitHub", "GitHub", "secret",
                  "Jeton « fine-grained » limité aux dépôts voulus : Contents + Pull requests."),
    EditableField("GITHUB_REPO", "Dépôt par défaut", "GitHub", "text", "owner/repo"),
    EditableField("GITHUB_ALLOWED_REPOS", "Autres dépôts autorisés", "GitHub", "text",
                  "Séparés par des virgules."),
)  # fmt: skip
BY_KEY = {f.key: f for f in FIELDS}
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_PLAIN = re.compile(r"^[A-Za-z0-9_./:@,+~-]*$")
UI_HEADER = "# ─── Réglages enregistrés depuis l'interface de Nexus ─────────────"


class SettingsField(BaseModel):
    key: str
    label: str
    group: Group
    kind: Kind
    help: str
    choices: list[str]
    #: Valeur effective (jamais pour un secret)
    value: str | None
    configured: bool
    #: Secret : « …abcd »
    hint: str | None = None
    source: Literal["fichier", "environnement", "défaut"]


class SettingsView(BaseModel):
    env_file: str
    fields: list[SettingsField]


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Clé → nouvelle valeur ; "" ou null = retirer du fichier (valeur par défaut)
    values: dict[str, str | None] = Field(min_length=1, max_length=len(FIELDS))


class SettingsError(ValueError):
    """Réglage refusé ; `fields` = message par clé."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k} : {v}" for k, v in fields.items()))
        self.fields = fields


def env_file_path() -> Path:
    """Le `.env` lu par Settings (relatif au dossier courant)."""
    return Path(str(Settings.model_config.get("env_file") or ".env")).resolve()


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if value[0] == '"' else inner
    return value.split(" #", 1)[0].strip()


def read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        match = _LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = _unquote(match.group(2))
    return values


def _quote(value: str) -> str:
    if _PLAIN.match(value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_env_file(path: Path, changes: dict[str, str | None]) -> None:
    """Remplace ou ajoute les clés (None = retirer), sans toucher au reste ; écriture atomique."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    pending = dict(changes)
    out: list[str] = []
    for line in lines:
        match = _LINE.match(line)
        key = match.group(1) if match and not line.lstrip().startswith("#") else None
        if key in pending:
            value = pending.pop(key)
            if value is not None:
                out.append(f"{key}={_quote(value)}")
            continue
        out.append(line)
    additions = [f"{k}={_quote(v)}" for k, v in pending.items() if v is not None]
    if additions:
        if UI_HEADER not in out:
            out += ["", UI_HEADER]
        out += additions
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out).rstrip("\n") + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def validate_changes(update: SettingsUpdate, current: Settings) -> dict[str, str | None]:
    """Contrôle des clés et des valeurs ; renvoie les changements normalisés (None = retirer)."""
    errors: dict[str, str] = {}
    changes: dict[str, str | None] = {}
    for key, raw in update.values.items():
        spec = BY_KEY.get(key)
        if spec is None:
            errors[key] = "réglage non modifiable depuis l'interface"
            continue
        value = None if raw is None else raw.strip()
        if value and ("\n" in value or "\r" in value or len(value) > 2000):
            errors[key] = "valeur invalide"
            continue
        if value and spec.kind == "url" and not re.match(r"^https?://[^\s/]+", value):
            errors[key] = "adresse attendue (http:// ou https://)"
            continue
        if value and spec.kind == "choice" and value not in spec.choices:
            errors[key] = f"choix possibles : {', '.join(c for c in spec.choices if c)}"
            continue
        if value and (problem := _cuisine_problem(key, value)):
            errors[key] = problem
            continue
        changes[key] = value or None
    if not errors:
        # Contrôle final par le modèle Settings lui-même (types, littéraux)
        merged = current.model_dump()
        for key, value in changes.items():
            merged[key.lower()] = value
        try:
            Settings.model_validate({k: v for k, v in merged.items() if v is not None})
        except ValidationError as exc:
            for err in exc.errors():
                loc = str(err["loc"][0]).upper() if err["loc"] else "?"
                errors[loc] = err["msg"]
    if errors:
        raise SettingsError(errors)
    return changes


def _cuisine_problem(key: str, value: str) -> str | None:
    """Atelier Cuisine : adresse HTTPS du projet, clé publique uniquement (RLS)."""
    from app.tools.cuisine import anon_key_problem, supabase_url_problem

    if key == "CUISINE_SUPABASE_URL":
        return supabase_url_problem(value)
    if key == "CUISINE_SUPABASE_ANON_KEY":
        return anon_key_problem(value)
    if key == "CUISINE_EMAIL" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return "adresse e-mail attendue"
    return None


def view(settings: Settings, path: Path) -> SettingsView:
    in_file = read_env_file(path)
    fields: list[SettingsField] = []
    for spec in FIELDS:
        current = getattr(settings, spec.attr, None)
        if isinstance(current, SecretStr):
            text: str | None = current.get_secret_value()
        else:
            text = None if current is None else str(current)
        source: Literal["fichier", "environnement", "défaut"] = (
            "environnement"
            if spec.key in os.environ
            else "fichier"
            if spec.key in in_file
            else "défaut"
        )
        fields.append(
            SettingsField(
                key=spec.key,
                label=spec.label,
                group=spec.group,
                kind=spec.kind,
                help=spec.help,
                choices=list(spec.choices),
                value=None if spec.kind == "secret" else (text or ""),
                configured=bool(text),
                hint=f"…{text[-4:]}" if spec.kind == "secret" and text and len(text) >= 8 else None,
                source=source,
            )
        )
    return SettingsView(env_file=str(path), fields=fields)
