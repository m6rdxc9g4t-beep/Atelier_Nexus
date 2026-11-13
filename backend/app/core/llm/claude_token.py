"""Jeton du forfait Claude (`claude setup-token`) : lu une fois, jamais montré.

Décision de l'utilisateur : « je veux que Claude forfait cli soit actif car c'est personnel ça
sera mon forfait Claude ». Sur un serveur, il n'y a pas de session `claude` connectée : la CLI
isolée s'authentifie avec le jeton d'un an que `claude setup-token` affiche, fourni au processus
par la variable d'environnement `CLAUDE_OAUTH_TOKEN`.

- Le jeton est lu **une seule fois** (au démarrage, `main.py`) puis **retiré de l'environnement
  du processus** : aucun autre sous-processus (serveur MCP de Tab, autre application ouverte…)
  n'en hérite. Seule la CLI Claude le reçoit, sous le nom `CLAUDE_CODE_OAUTH_TOKEN`
  (`claude_code_provider.py`).
- App de bureau : la mise à jour au lancement (git, npm, pip) se fait avant l'import de
  `main.py`, donc avant ce retrait ; ses commandes reçoivent un environnement sans le jeton
  (`desktop_update.command_environment`, bibliothèque standard : ce module-ci dépend de pydantic).
- Il n'est lu que dans l'environnement : ni dans le `.env` (fichier réécrit par l'écran
  Réglages), ni dans `Settings`. Il n'est écrit nulle part, n'apparaît dans aucune réponse d'API,
  erreur, journal ou argument de ligne de commande (`SecretStr` : jamais dans un `repr`).
- Sans cette variable, rien ne change (clé API ou session `claude` de l'utilisateur).

Bibliothèque standard et pydantic uniquement.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import MutableMapping
from pathlib import Path

from pydantic import SecretStr

#: Variable lue par Nexus (contrat commun des applications de la suite)
TOKEN_ENV = "CLAUDE_OAUTH_TOKEN"
#: Variable que lit la CLI Claude Code : posée dans SON environnement seulement
CLI_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
#: Dossier privé de la CLI en mode jeton, sous le dossier de données de Nexus (celui du `.env`)
PRIVATE_HOME_NAME = "claude-forfait"
MASK = "[jeton masqué]"
#: Forme des jetons d'Anthropic (forfait `sk-ant-oat…`, clé `sk-ant-api…`) : masquée dans tout
#: message d'erreur, même si ce n'est pas le jeton de ce processus
_TOKEN_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")

#: (jeton,) une fois lu ; None tant que l'environnement n'a pas été lu
_captured: tuple[SecretStr | None] | None = None


def capture_token(environ: MutableMapping[str, str] | None = None) -> SecretStr | None:
    """Lit `CLAUDE_OAUTH_TOKEN` une seule fois et le retire de l'environnement du processus.

    Les appels suivants rendent le jeton gardé en mémoire, sans relire l'environnement."""
    global _captured
    if _captured is None:
        env = os.environ if environ is None else environ
        raw = (env.pop(TOKEN_ENV, "") or "").strip()
        _captured = (SecretStr(raw) if raw else None,)
    return _captured[0]


def subscription_token() -> SecretStr | None:
    """Le jeton du forfait s'il a été fourni au démarrage, sinon None."""
    return capture_token()


def forget_token() -> None:
    """Oublie le jeton lu (tests : chaque test repart de son propre environnement)."""
    global _captured
    _captured = None


def scrub(text: str, token: SecretStr | None) -> str:
    """Le texte sans le jeton (ni rien qui ait la forme d'un jeton d'Anthropic)."""
    if token is not None:
        text = text.replace(token.get_secret_value(), MASK)
    return _TOKEN_SHAPE.sub(MASK, text)


def private_home(data_dir: Path) -> Path:
    """Dossier privé de la CLI en mode jeton (`HOME` ; `CLAUDE_CONFIG_DIR` = son `.claude`)."""
    return data_dir / PRIVATE_HOME_NAME


def ensure_private_home(home: Path) -> Path:
    """Crée le dossier privé et son `.claude` (droits 700) ; rend le dossier de configuration."""
    config = home / ".claude"
    for folder in (home, config):
        folder.mkdir(parents=True, exist_ok=True)
        # Hors Windows : lisible par ce seul utilisateur (sous Windows, droits du profil)
        if os.name != "nt" and stat.S_IMODE(folder.stat().st_mode) != 0o700:
            folder.chmod(0o700)
    return config
