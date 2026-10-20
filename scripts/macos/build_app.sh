#!/usr/bin/env bash
# Construit « Atelier Nexus.app » : une application macOS autonome, à double-cliquer.
#
#     ./scripts/macos/build_app.sh                 # → ~/Applications/Atelier Nexus.app + raccourci sur le Bureau
#     ./scripts/macos/build_app.sh ~/Desktop       # directement sur le Bureau
#     ./scripts/macos/build_app.sh --no-shortcut   # sans raccourci sur le Bureau
#
# L'application contient le code du backend et l'interface compilée (rien ne dépend du dépôt
# ensuite). À la première ouverture, son lanceur crée un environnement Python dans
# ~/Library/Application Support/Atelier Nexus/venv et y installe les dépendances (2 à 3 min) ;
# il le refait seul quand requirements.txt change. Données et réglages restent dans ce même
# dossier : reconstruire ou remplacer l'application ne les touche pas.
#
# Prérequis pour construire : Node.js (npm). Pour utiliser : Python 3.12+ (python.org,
# Homebrew, conda…) ou uv ; le lanceur les cherche lui-même.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$HOME/Applications"
SHORTCUT=1
for arg in "$@"; do
  case "$arg" in
    --no-shortcut) SHORTCUT=0 ;;
    -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
    *) DEST="$arg" ;;
  esac
done
APP="$DEST/Atelier Nexus.app"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mErreur : %s\033[0m\n' "$*" >&2; exit 1; }

if [[ "$(uname)" != "Darwin" && "${ATELIER_BUILD_ANY_OS:-}" != "1" ]]; then
  fail "ce script construit une application macOS : lancez-le sur le Mac (ou ATELIER_BUILD_ANY_OS=1)."
fi

say "1/3 · Interface (export statique)"
if command -v npm >/dev/null; then
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund --loglevel=error \
    && rm -rf out && NEXUS_EXPORT=1 NEXT_PUBLIC_API_URL='' npm run build --silent >/dev/null)
elif [[ -f "$ROOT/frontend/out/index.html" ]]; then
  echo "npm introuvable : interface déjà compilée réutilisée (frontend/out)."
else
  fail "npm introuvable : installez Node.js (https://nodejs.org) pour compiler l'interface."
fi
[[ -f "$ROOT/frontend/out/index.html" ]] || fail "la compilation de l'interface a échoué."

say "2/3 · Application ($APP)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/app/__init__.py")"
mkdir -p "$DEST"
rm -rf "$APP"
CODE="$APP/Contents/Resources/nexus"
mkdir -p "$APP/Contents/MacOS" "$CODE/backend" "$CODE/frontend"
for item in app migrations main.py desktop.py alembic.ini requirements.txt requirements-desktop.txt .env.example; do
  cp -R "$ROOT/backend/$item" "$CODE/backend/"
done
find "$CODE" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -R "$ROOT/frontend/out" "$CODE/frontend/out"
cp "$ROOT/scripts/macos/AtelierNexus.icns" "$APP/Contents/Resources/AtelierNexus.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Atelier Nexus</string>
  <key>CFBundleDisplayName</key><string>Atelier Nexus</string>
  <key>CFBundleIdentifier</key><string>fr.atelier-nexus.app</string>
  <key>CFBundleExecutable</key><string>atelier-nexus</string>
  <key>CFBundleIconFile</key><string>AtelierNexus</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleDevelopmentRegion</key><string>fr</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Atelier Nexus — agents IA de la suite Atelier</string>
</dict>
</plist>
PLIST

cp "$ROOT/scripts/macos/launcher.sh" "$APP/Contents/MacOS/atelier-nexus"
chmod +x "$APP/Contents/MacOS/atelier-nexus"

say "3/3 · Enregistrement"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[[ -x "$LSREGISTER" ]] && "$LSREGISTER" -f "$APP" >/dev/null 2>&1 || true
command -v xattr >/dev/null && xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

DESKTOP="$HOME/Desktop"
if [[ "$SHORTCUT" == 1 && -d "$DESKTOP" && "$(cd "$DEST" && pwd)" != "$(cd "$DESKTOP" && pwd)" ]]; then
  ln -sfn "$APP" "$DESKTOP/Atelier Nexus.app"
  echo "Raccourci : $DESKTOP/Atelier Nexus.app"
fi

say "✓ Atelier Nexus.app est prête : $APP"
cat <<EOF

  • Double-cliquez sur « Atelier Nexus ». La première ouverture prépare Python (2 à 3 minutes,
    une notification l'indique) ; les suivantes sont immédiates.
  • Réglages (clé Claude, adresses des apps) : menu Réglages de l'application, ou
    ~/Library/Application Support/Atelier Nexus/.env
  • Journal : ~/Library/Logs/Atelier Nexus/atelier-nexus.log
  • Après une mise à jour du code (git pull) : relancez ce script.
EOF
if [[ "$(uname)" == "Darwin" ]]; then open -R "$APP" || true; fi
