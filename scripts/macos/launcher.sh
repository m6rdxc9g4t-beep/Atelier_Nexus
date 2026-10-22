#!/bin/bash
# Lanceur d'« Atelier Nexus.app », exécuté DEPUIS LE DÉPÔT par le point d'entrée de l'app
# (Contents/MacOS/atelier-nexus = scripts/macos/app_entry.sh). Mise à jour au lancement selon
# docs/apps/mise-a-jour-bureau.md : après un git pull, l'app se met à jour toute seule.
#
# 1. Trouve un Python 3.12+ (Homebrew, python.org, conda, uv…) : une application lancée depuis
#    le Finder n'hérite pas du PATH du terminal, on cherche donc aux emplacements habituels.
# 2. Environnement Python de l'app (~/Library/Application Support/Atelier Nexus/venv) : créé au
#    premier lancement, refait quand backend/requirements*.txt changent (backend/app/
#    desktop_update.py venv) ; en cas d'échec, l'ancien est remis en place.
# 3. Lance la fenêtre (backend/desktop.py --mise-a-jour) : écran « Mise à jour… » si l'interface
#    est à recompiler (npm ci, compilation), puis l'app.
#
# Jamais de git pull, jamais de donnée touchée. Journaux : ~/Library/Logs/Atelier Nexus/.
# Surcharges (tests, simulation hors macOS) : NEXUS_REPO, NEXUS_HOME, NEXUS_LOG_DIR,
# NEXUS_PYTHON (Python de base), NEXUS_NPM.
#
#     launcher.sh              # lancement normal (fenêtre)
#     launcher.sh --preparer   # mise à jour seulement, dans le terminal (build_app.sh)

REPO="${NEXUS_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
SUPPORT="${NEXUS_HOME:-$HOME/Library/Application Support/Atelier Nexus}"
LOG_DIR="${NEXUS_LOG_DIR:-$HOME/Library/Logs/Atelier Nexus}"
VENV="$SUPPORT/venv"
LOG="$LOG_DIR/atelier-nexus.log"
UPDATE_LOG="$LOG_DIR/mise-a-jour.log"
UPDATE="$REPO/backend/app/desktop_update.py"
UPDATE_LOG_SHOWN="${UPDATE_LOG/#$HOME/\~}"
# Le backend (desktop.py, desktop_update.py) lit les mêmes dossiers
export NEXUS_HOME="$SUPPORT" NEXUS_LOG_DIR="$LOG_DIR"

PREPARE=0
for arg in "$@"; do [[ "$arg" == "--preparer" ]] && PREPARE=1; done

# Outils utiles aux agents et à la mise à jour (node/npm, ollama, claude…)
export PATH="$HOME/.homebrew/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

mkdir -p "$LOG_DIR" "$SUPPORT"
if [[ -f "$LOG" && $(wc -c <"$LOG") -gt 5000000 ]]; then
  mv -f "$LOG" "$LOG.1"
fi
echo "--- $(date '+%F %T') : lancement ($REPO)" >>"$LOG"

# Messages : arguments d'osascript (jamais de script construit avec du texte) ; terminal sinon
alert() {
  if [[ "$PREPARE" == 1 ]] || ! /usr/bin/osascript - "$1" >/dev/null 2>&1 <<'OSA'; then
on run argv
  display alert "Atelier Nexus" message (item 1 of argv) as critical
end run
OSA
    echo "Atelier Nexus : $1" >&2
  fi
}
notify() {
  if [[ "$PREPARE" == 1 ]]; then echo "$1"; return; fi
  /usr/bin/osascript - "$1" >/dev/null 2>&1 <<'OSA' || true
on run argv
  display notification (item 1 of argv) with title "Atelier Nexus"
end run
OSA
}
# Vrai si l'utilisateur choisit d'ouvrir l'app avec la version précédente
choose_previous() {
  local answer
  [[ "$PREPARE" == 1 ]] && { echo "Atelier Nexus : $1" >&2; return 1; }
  answer="$(/usr/bin/osascript - "$1" 2>/dev/null <<'OSA'
on run argv
  display dialog (item 1 of argv) with title "Atelier Nexus" with icon caution buttons {"Quitter", "Ouvrir quand même avec la version précédente"} default button 2
end run
OSA
)" || { echo "Atelier Nexus : $1" >&2; return 1; }
  [[ "$answer" == *"version précédente"* ]]
}

if [[ ! -f "$UPDATE" || ! -f "$REPO/backend/desktop.py" ]]; then
  alert "Le dépôt d'Atelier Nexus est introuvable ou incomplet ($REPO). Relancez scripts/macos/build_app.sh depuis le dépôt."
  exit 1
fi

# Version (majeur*100 + mineur) d'un interpréteur, ou rien s'il ne répond pas
py_version() {
  "$1" -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>/dev/null
}

find_python() {
  if [[ -n "${NEXUS_PYTHON:-}" ]]; then echo "$NEXUS_PYTHON"; return; fi
  local best="" best_v=0 v c
  local candidates=(
    "$HOME"/.homebrew/bin/python3.1[2-9] "$HOME"/.homebrew/bin/python3
    /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3
    /usr/local/bin/python3.14 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3
    /Library/Frameworks/Python.framework/Versions/3.1[2-9]/bin/python3
    "$HOME"/.local/share/uv/python/cpython-3.1[2-9]*/bin/python3
    "$HOME"/opt/anaconda3/bin/python /opt/anaconda3/bin/python "$HOME"/anaconda3/bin/python
    "$HOME"/miniconda3/bin/python "$HOME"/miniforge3/bin/python /opt/homebrew/Caskroom/miniforge/base/bin/python
    "$HOME"/opt/anaconda3/envs/*/bin/python "$HOME"/anaconda3/envs/*/bin/python "$HOME"/miniconda3/envs/*/bin/python
    "$HOME"/.conda/envs/*/bin/python "$HOME"/.pyenv/versions/3.1[2-9]*/bin/python3
  )
  local path_py
  path_py="$(command -v python3 2>/dev/null)" && candidates+=("$path_py")
  for c in "${candidates[@]}"; do
    [[ -x "$c" ]] || continue
    v="$(py_version "$c")"
    [[ -n "$v" && "$v" -ge 312 && "$v" -gt "$best_v" ]] && { best="$c"; best_v="$v"; }
  done
  if [[ -z "$best" ]] && command -v uv >/dev/null; then
    echo "Python 3.12+ introuvable : uv l'installe" >>"$UPDATE_LOG"
    uv python install --quiet 3.13 >>"$UPDATE_LOG" 2>&1 && best="$(uv python find 3.13 2>>"$UPDATE_LOG")"
  fi
  [[ -n "$best" ]] && echo "$best"
}

# ─── Environnement Python (avant la fenêtre : elle en dépend) ───
venv_ok() {
  [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -I "$UPDATE" venv --check >/dev/null 2>&1
}

if ! venv_ok; then
  py="$(find_python)"
  if [[ -z "$py" ]]; then
    alert "Python 3.12 ou plus récent est introuvable. Installez-le (python.org, ou « brew install python@3.13 » dans le Terminal), puis rouvrez Atelier Nexus."
    exit 1
  fi
  notify "Mise à jour : installation des dépendances Python (2 à 3 minutes)…"
  "$py" -I "$UPDATE" venv
  case $? in
    0) ;;
    3)
      choose_previous "L'installation des dépendances Python a échoué (connexion Internet ?). L'environnement précédent est conservé ; le prochain lancement réessaiera. Journal : $UPDATE_LOG_SHOWN" \
        || exit 1 ;;
    *)
      alert "L'installation des dépendances Python a échoué (connexion Internet ?). Journal : $UPDATE_LOG_SHOWN"
      exit 1 ;;
  esac
fi

cd "$REPO/backend" || exit 1
if [[ "$PREPARE" == 1 ]]; then
  # Terminal (build_app.sh) : étapes et erreurs affichées ; détail des commandes dans le journal
  exec "$VENV/bin/python" desktop.py --mise-a-jour "$@"
fi
# exec : le processus Python reste celui de l'application (une seule icône dans le Dock)
exec "$VENV/bin/python" desktop.py --mise-a-jour "$@" >>"$LOG" 2>&1
