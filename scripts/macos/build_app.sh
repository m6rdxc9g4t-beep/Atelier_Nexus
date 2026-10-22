#!/usr/bin/env bash
# Construit « Atelier Nexus.app » : un lanceur macOS, à double-cliquer, branché sur ce dépôt.
#
#     ./scripts/macos/build_app.sh                 # → ~/Applications/Atelier Nexus.app + raccourci sur le Bureau
#     ./scripts/macos/build_app.sh ~/Desktop       # directement sur le Bureau
#     ./scripts/macos/build_app.sh --no-shortcut   # sans raccourci sur le Bureau
#
# L'application ne contient pas de copie du code : elle lance celui du dépôt (chemin enregistré
# dans Contents/Resources/repo-path) et se met à jour toute seule à son ouverture après un git
# pull (docs/apps/mise-a-jour-bureau.md). Ce script ne se relance qu'une fois, ou si le dépôt
# change de place. Il fait la première mise à jour (environnement Python, npm ci, compilation de
# l'interface) dans le terminal. Données et réglages restent dans
# ~/Library/Application Support/Atelier Nexus : construire ou remplacer l'app ne les touche pas,
# y compris une ancienne app « copie figée ».
#
# Prérequis : Node.js (npm) et Python 3.12+ (python.org, Homebrew, conda…) ou uv ; le lanceur
# les cherche lui-même (~/.homebrew, /opt/homebrew, /usr/local, nvm…).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$HOME/Applications"
SHORTCUT=1
for arg in "$@"; do
  case "$arg" in
    --no-shortcut) SHORTCUT=0 ;;
    -h | --help) sed -n '2,19p' "$0"; exit 0 ;;
    *) DEST="$arg" ;;
  esac
done
APP="$DEST/Atelier Nexus.app"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mErreur : %s\033[0m\n' "$*" >&2; exit 1; }

if [[ "$(uname)" != "Darwin" && "${ATELIER_BUILD_ANY_OS:-}" != "1" ]]; then
  fail "ce script construit une application macOS : lancez-le sur le Mac (ou ATELIER_BUILD_ANY_OS=1)."
fi

# Première mise à jour AVANT de toucher à l'app existante : en cas d'échec, elle reste intacte.
say "1/3 · Première mise à jour (environnement Python, interface)"
NEXUS_REPO="$ROOT" /bin/bash "$ROOT/scripts/macos/launcher.sh" --preparer \
  || fail "la mise à jour a échoué (détails : ~/Library/Logs/Atelier Nexus/mise-a-jour.log)."

say "2/3 · Application ($APP)"
if [[ -d "$APP/Contents/Resources/nexus" ]]; then
  echo "Ancienne application (copie figée du code) remplacée par un lanceur ; données conservées."
fi
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/app/__init__.py")"
mkdir -p "$DEST"
rm -rf "$APP"  # l'app seulement : les données sont dans ~/Library/Application Support/Atelier Nexus
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
printf '%s\n' "$ROOT" >"$APP/Contents/Resources/repo-path"
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

cp "$ROOT/scripts/macos/app_entry.sh" "$APP/Contents/MacOS/atelier-nexus"
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

  • Double-cliquez sur « Atelier Nexus ». Elle lance le code de ce dépôt : $ROOT
  • Après un git pull, relancez simplement l'app : elle se met à jour toute seule (écran
    « Mise à jour… » le temps de recompiler). Ne relancez ce script que si le dépôt change de place.
  • Réglages (clé Claude, adresses des apps) : menu Réglages de l'application, ou
    ~/Library/Application Support/Atelier Nexus/.env
  • Journaux : ~/Library/Logs/Atelier Nexus/ (atelier-nexus.log, mise-a-jour.log)
EOF
if [[ "$(uname)" == "Darwin" ]]; then open -R "$APP" || true; fi
