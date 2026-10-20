#!/bin/bash
# Lanceur d'« Atelier Nexus.app » (copié dans Contents/MacOS/atelier-nexus par build_app.sh).
#
# 1. Trouve un Python 3.12+ (Homebrew, python.org, conda, uv…) : une application lancée depuis
#    le Finder n'hérite pas du PATH du terminal, on cherche donc aux emplacements habituels.
# 2. Première ouverture (ou dépendances modifiées) : crée l'environnement Python dans
#    ~/Library/Application Support/Atelier Nexus/venv et installe les dépendances.
# 3. Lance la fenêtre (backend/desktop.py). Journal : ~/Library/Logs/Atelier Nexus/.

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
CODE="$CONTENTS/Resources/nexus"
SUPPORT="$HOME/Library/Application Support/Atelier Nexus"
VENV="$SUPPORT/venv"
STAMP="$VENV/.nexus-requirements"
LOG_DIR="$HOME/Library/Logs/Atelier Nexus"
LOG="$LOG_DIR/atelier-nexus.log"

# Outils utiles aux agents (node pour le serveur MCP d'Atelier Tab, ollama, claude…)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

mkdir -p "$LOG_DIR" "$SUPPORT"
if [[ -f "$LOG" && $(wc -c <"$LOG") -gt 5000000 ]]; then
  mv -f "$LOG" "$LOG.1"
fi
echo "--- $(date '+%F %T') : lancement ($CODE)" >>"$LOG"

alert() {
  /usr/bin/osascript -e "display alert \"Atelier Nexus\" message \"$1\" as critical" >/dev/null 2>&1 || echo "$1" >&2
}
notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Atelier Nexus\"" >/dev/null 2>&1 || true
}

# Version (majeur*100 + mineur) d'un interpréteur, ou rien s'il ne répond pas
py_version() {
  "$1" -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>/dev/null
}

find_python() {
  local best="" best_v=0 v c
  local candidates=(
    /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3
    /usr/local/bin/python3.14 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3
    "$HOME"/.homebrew/bin/python3*
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
  [[ -n "$best" ]] && echo "$best"
}

requirements_hash() {
  cat "$CODE/backend/requirements.txt" "$CODE/backend/requirements-desktop.txt" | shasum | cut -d' ' -f1
}

install_env() {
  local py hash
  hash="$(requirements_hash)"
  [[ -x "$VENV/bin/python" && -f "$STAMP" && "$(cat "$STAMP")" == "$hash" ]] && return 0
  notify "Préparation de Python pour la première ouverture (2 à 3 minutes)…"
  rm -rf "$VENV"
  py="$(find_python)"
  if [[ -n "$py" ]]; then
    echo "Environnement Python : $py ($("$py" --version 2>&1))" >>"$LOG"
    "$py" -m venv "$VENV" >>"$LOG" 2>&1 \
      && "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >>"$LOG" 2>&1 \
      && "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
        -r "$CODE/backend/requirements.txt" -r "$CODE/backend/requirements-desktop.txt" >>"$LOG" 2>&1 \
      || return 1
  elif command -v uv >/dev/null; then
    echo "Python 3.12+ introuvable : uv l'installe" >>"$LOG"
    uv venv --quiet --python 3.13 "$VENV" >>"$LOG" 2>&1 \
      && uv pip install --quiet --python "$VENV/bin/python" \
        -r "$CODE/backend/requirements.txt" -r "$CODE/backend/requirements-desktop.txt" >>"$LOG" 2>&1 \
      || return 1
  else
    return 2
  fi
  echo "$hash" >"$STAMP"
}

install_env
case $? in
  0) ;;
  2)
    alert "Python 3.12 ou plus récent est introuvable. Installez-le (python.org, ou « brew install python@3.13 » dans le Terminal), puis rouvrez Atelier Nexus."
    exit 1 ;;
  *)
    rm -rf "$VENV"
    alert "L'installation des dépendances a échoué (connexion Internet ?). Détails : ~/Library/Logs/Atelier Nexus/atelier-nexus.log"
    exit 1 ;;
esac

cd "$CODE/backend" || exit 1
export NEXUS_FRONTEND_DIST="$CODE/frontend/out"
# exec : le processus Python reste celui de l'application (une seule icône dans le Dock)
exec "$VENV/bin/python" desktop.py "$@" >>"$LOG" 2>&1
