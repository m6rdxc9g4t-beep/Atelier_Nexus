#!/bin/bash
# Point d'entrée d'« Atelier Nexus.app » (copié dans Contents/MacOS/atelier-nexus par build_app.sh).
#
# L'application n'est qu'un lanceur : elle exécute scripts/macos/launcher.sh du dépôt dont le
# chemin est enregistré dans Contents/Resources/repo-path (NEXUS_REPO pour le surcharger). Le code
# lancé est donc toujours celui du dépôt : après un git pull, rouvrir l'app suffit.

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${NEXUS_REPO:-$(cat "$CONTENTS/Resources/repo-path" 2>/dev/null)}"
LAUNCHER="$REPO/scripts/macos/launcher.sh"

if [[ -z "$REPO" || ! -f "$LAUNCHER" ]]; then
  message="Le dépôt d'Atelier Nexus est introuvable (${REPO:-chemin non enregistré}). S'il a été déplacé, relancez scripts/macos/build_app.sh depuis son nouvel emplacement."
  echo "Atelier Nexus : $message" >&2
  # NEXUS_NO_DIALOG=1 (tests) : message sur la sortie d'erreur seulement, aucune fenêtre ouverte
  if [[ "${NEXUS_NO_DIALOG:-}" != 1 ]]; then
    /usr/bin/osascript - "$message" >/dev/null 2>&1 <<'OSA' || true
on run argv
  display alert "Atelier Nexus" message (item 1 of argv) as critical
end run
OSA
  fi
  exit 1
fi

export NEXUS_REPO="$REPO"
exec /bin/bash "$LAUNCHER" "$@"
