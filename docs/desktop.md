# Application de bureau macOS (Étape 9)

« Atelier Nexus.app » s'ouvre d'un double-clic, comme les autres apps de la suite : une fenêtre native (pywebview),
une icône dans le Dock, sans terminal ni Docker. Le backend tourne dans l'application et sert lui-même l'interface.

## Construire et installer

Sur le Mac, depuis le dépôt (Node.js requis pour compiler l'interface) :

```bash
./scripts/macos/build_app.sh               # ~/Applications/Atelier Nexus.app + raccourci sur le Bureau
./scripts/macos/build_app.sh ~/Desktop     # directement sur le Bureau
./scripts/macos/build_app.sh --no-shortcut # sans raccourci
```

L'application est **autonome** : elle contient le backend et l'interface compilée (`NEXUS_EXPORT=1`, export statique
de Next.js). Elle ne dépend plus du dépôt ; relancez le script après une mise à jour du code.

## Premier lancement

Le lanceur (`scripts/macos/launcher.sh`, copié dans `Contents/MacOS/atelier-nexus`) :

1. cherche un **Python 3.12+** : Homebrew, python.org, conda (base et environnements), pyenv, uv ; à défaut `uv`
   en installe un ;
2. crée l'environnement `~/Library/Application Support/Atelier Nexus/venv` et installe les dépendances (2 à 3 min,
   une notification l'annonce). Il le refait seul quand `requirements.txt` change ;
3. lance `backend/desktop.py`.

Si Python est introuvable ou que l'installation échoue, une alerte dit quoi faire ; détails dans le journal.

## Où sont les données

| Chemin | Contenu |
|---|---|
| `~/Library/Application Support/Atelier Nexus/.env` | Réglages (créé au premier lancement depuis `.env.example`, droits 600) : modifiables depuis la **roue dentée** de l'interface ([`settings.md`](settings.md)), ou à la main (menu Réglages → « Ouvrir le fichier de réglages »). |
| `…/Atelier Nexus/nexus.db` | Base SQLite : agents personnalisés, conversations, artefacts (imposée, quel que soit `DATABASE_URL`) |
| `…/Atelier Nexus/webview/` | Stockage de la fenêtre (thème, dernière conversation par agent) |
| `…/Atelier Nexus/venv/` | Environnement Python |
| `~/Library/Logs/Atelier Nexus/atelier-nexus.log` | Journal (5 Mo, l'ancien gardé en `.1`) |

Remplacer ou reconstruire l'application ne touche à rien de tout cela.

## Comportement

- Serveur sur `127.0.0.1` uniquement, port 8100 s'il est libre, sinon un port libre : l'interface utilise des adresses
  relatives (`NEXT_PUBLIC_API_URL` vide), elle fonctionne sur n'importe quel port.
- Fermer la fenêtre ou ⌘Q arrête le serveur.
- Fond de la fenêtre avant l'affichage de l'interface : celui de la charte néon (`WINDOW_BACKGROUND` dans
  `app/desktop.py`, `#fbf3f2` clair / `#120c0d` sombre selon l'apparence de macOS), comme la page d'erreur de démarrage.
- Si Atelier Tab est installé (`/Applications/Atelier_Tab.app`), l'écriture dans Tab est activée sans réglage
  (`TAB_MCP_COMMAND`), sauf si le `.env` en choisit une autre.
- Pont JavaScript (`frontend/src/lib/desktop.ts` ↔ `DesktopApi`) : « Enregistrer sous » natif pour les artefacts
  (`saveFile`), liens externes dans le navigateur ; l'adresse d'une app de la suite ouvre son application si elle est
  installée (`openExternal`). Dans la fenêtre, `a.download` et `window.open` sont ignorés par WKWebView : toujours
  passer par ces deux fonctions.

Sans fenêtre : `cd backend && python desktop.py --navigateur`.

## Vérifier

```bash
cd backend && pytest tests/test_desktop.py      # dossier, réglages, pont, interface servie
ATELIER_BUILD_ANY_OS=1 ./scripts/macos/build_app.sh /tmp/essai --no-shortcut   # assemblage hors macOS
```
