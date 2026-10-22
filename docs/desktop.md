# Application de bureau macOS (Étapes 9 et 22)

« Atelier Nexus.app » s'ouvre d'un double-clic, comme les autres apps de la suite : une fenêtre native (pywebview),
une icône dans le Dock, sans terminal ni Docker. Le backend tourne dans l'application et sert lui-même l'interface.

## Construire et installer (une seule fois)

Sur le Mac, depuis le dépôt (Node.js et Python 3.12+ requis ; le lanceur les cherche lui-même) :

```bash
./scripts/macos/build_app.sh               # ~/Applications/Atelier Nexus.app + raccourci sur le Bureau
./scripts/macos/build_app.sh ~/Desktop     # directement sur le Bureau
./scripts/macos/build_app.sh --no-shortcut # sans raccourci
```

L'application est un **lanceur branché sur le dépôt** : elle ne contient aucune copie du code, seulement le chemin du
dépôt (`Contents/Resources/repo-path`) et un point d'entrée (`scripts/macos/app_entry.sh`, copié dans
`Contents/MacOS/atelier-nexus`) qui exécute `scripts/macos/launcher.sh` **du dépôt**. Le script fait la première mise à
jour dans le terminal (environnement Python, `npm ci`, compilation) **avant** de remplacer l'app : en cas d'échec,
l'ancienne reste intacte. Il remplace aussi proprement une ancienne app « copie figée » (`Contents/Resources/nexus`),
sans toucher aux données. Ne le relancez que si le dépôt change de place (l'app affiche alors « dépôt introuvable »).

## Mise à jour automatique (après un `git pull`)

Contrat commun : [`apps/mise-a-jour-bureau.md`](apps/mise-a-jour-bureau.md) (`SUITE.md` §8), modèle d'Atelier Projets.
**Après un `git pull`, relancez simplement l'app.** À chaque ouverture :

1. **Environnement Python** (`launcher.sh`, avant la fenêtre : elle en dépend) — Python 3.12+ cherché dans Homebrew
   (`~/.homebrew`, `/opt/homebrew`, `/usr/local`), python.org, conda, pyenv, uv (à défaut `uv` en installe un).
   `backend/app/desktop_update.py venv` le crée au premier lancement et le refait quand `backend/requirements.txt` ou
   `requirements-desktop.txt` changent (empreinte dans `venv/.nexus-requirements`, compatible avec l'ancien lanceur) ;
   l'ancien est mis de côté puis **remis en place si l'installation échoue** : une alerte propose alors « Ouvrir quand
   même avec la version précédente » ou « Quitter ». Une notification annonce l'étape (2 à 3 min).
2. **Interface** (`desktop.py --mise-a-jour`, fonctions pures de `app/desktop_update.py`) — état du dépôt = commit
   courant (`git rev-parse HEAD`) + contenu des fichiers suivis modifiés localement (`git diff --name-only HEAD`) ;
   empreinte de `frontend/package-lock.json` à part. Comparés au **tampon** de la dernière mise à jour réussie :

   | Changement | Étapes |
   |---|---|
   | aucun | lancement direct, rien n'est recompilé |
   | commit, ou modification locale non commitée | compilation |
   | `package-lock.json` (ou `node_modules` absent) | `npm ci` puis compilation |
   | `requirements*.txt` | environnement Python (étape 1) |

   Pendant ces étapes, la fenêtre affiche l'écran **« Mise à jour… »** avec l'étape en cours. La compilation
   (`NEXUS_EXPORT=1 NEXT_PUBLIC_API_URL='' npm run build`) sort dans `frontend/out`, est déplacée dans
   `…/Atelier Nexus/interface/build-…`, puis le lien `interface/courante` est remplacé **atomiquement** : la compilation
   précédente reste servie tant que la nouvelle n'a pas entièrement réussi. Le tampon n'est écrit qu'après.
3. **Lancement normal** : serveur local, migrations Alembic au démarrage (inchangé), interface.

**Échec** (réseau, compilation, Node.js introuvable) : message en français, chemin du journal
`~/Library/Logs/Atelier Nexus/mise-a-jour.log`, bouton « Ouvrir quand même avec la version précédente » si une
compilation existe, et « Quitter ». Tampon inchangé : le lancement suivant réessaie.

Garde-fous : **jamais de `git pull` automatique** (seul l'utilisateur fait évoluer le dépôt) ; **aucune donnée touchée**
(seuls `venv/`, `interface/` et `mise-a-jour/` du dossier de l'app sont écrits, plus `frontend/node_modules` et
`frontend/out` du dépôt, ignorés par git) ; réseau seulement pour `npm ci` et `pip install` ; **verrou** (`flock` sur
`mise-a-jour/verrou`) : une seule mise à jour à la fois, une deuxième ouverture attend puis ne refait rien.
`npm` est cherché sans dépendre du PATH du Finder : `NEXUS_NPM`, PATH, shell de connexion zsh (`zsh -lc`, puis `-lic`),
`~/.homebrew/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `~/.volta/bin`, nvm (version la plus récente).
Évitez de lancer l'app pendant un `npm run dev` qui recompile : la compilation de l'app réutilise `frontend/.next`.

## Où sont les données

| Chemin | Contenu |
|---|---|
| `~/Library/Application Support/Atelier Nexus/.env` | Réglages (créé au premier lancement depuis `.env.example`, droits 600) : modifiables depuis la **roue dentée** de l'interface ([`settings.md`](settings.md)), ou à la main (menu Réglages → « Ouvrir le fichier de réglages »). |
| `…/Atelier Nexus/nexus.db` | Base SQLite : agents personnalisés, conversations, artefacts (imposée, quel que soit `DATABASE_URL`) |
| `…/Atelier Nexus/webview/` | Stockage de la fenêtre (thème, dernière conversation par agent) |
| `…/Atelier Nexus/venv/` | Environnement Python |
| `…/Atelier Nexus/interface/` | Interface compilée servie (`courante` → `build-…`) |
| `…/Atelier Nexus/mise-a-jour/` | Tampon de la dernière mise à jour réussie (`etat.json`) et verrou |
| `~/Library/Logs/Atelier Nexus/atelier-nexus.log` | Journal (5 Mo, l'ancien gardé en `.1`) |
| `~/Library/Logs/Atelier Nexus/mise-a-jour.log` | Journal des mises à jour (commandes et leur sortie) |

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
  installée (`openExternal` ; ports locaux `SUITE_BUNDLES`, apps en ligne `SUITE_ONLINE_BUNDLES` : Atelier Cuisine
  `https://atelier-cuisine-iota.vercel.app` → `fr.ateliercuisine.app`). Dans la fenêtre, `a.download` et `window.open` sont ignorés par WKWebView : toujours
  passer par ces deux fonctions.

Sans fenêtre : `cd backend && python desktop.py --navigateur` (sans mise à jour ; ajouter `--mise-a-jour` pour la faire
d'abord). Mise à jour seule, dans le terminal : `./scripts/macos/launcher.sh --preparer`.

## Vérifier

```bash
cd backend && pytest tests/test_desktop.py tests/test_desktop_update.py   # dont une simulation complète du lanceur
ATELIER_BUILD_ANY_OS=1 ./scripts/macos/build_app.sh /tmp/essai --no-shortcut   # assemblage hors macOS
```

Surcharges pour les tests et la simulation hors macOS : `NEXUS_REPO` (dépôt), `NEXUS_HOME` (dossier de l'app),
`NEXUS_LOG_DIR` (journaux), `NEXUS_PYTHON` (Python de base), `NEXUS_NPM` (npm). `test_desktop_update.py` lance le vrai
`launcher.sh --preparer` sur un faux dépôt git avec un faux npm (environnement Python réel, dépendances vides).
