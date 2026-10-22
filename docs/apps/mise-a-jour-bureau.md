# Mise à jour automatique des apps de bureau — copie du contrat commun

Copie de la section 8 de `docs/SUITE.md` (identique dans Atelier_Viz, atelier-tab et Atelier_Projets). Ne pas l'éditer ici : la modifier dans les trois dépôts puis recopier.

## 8. Mise à jour automatique des apps de bureau

Décision de l'utilisateur : **après un `git pull`, chaque app de bureau se met à jour toute seule à son lancement suivant**,
comme Atelier Projets (`desktop/lib/prepare.cjs`, modèle de référence). Aucune commande à retaper, aucune app à reconstruire.

### 8.1 Principe
- L'app installée (`.app`) est un **lanceur** qui connaît le chemin du dépôt ; le code exécuté est celui du dépôt, pas une copie
  figée. Le lanceur ne se reconstruit qu'une fois (ou si le dépôt change de place).
- Au lancement, l'app calcule l'**état du dépôt** : empreinte du commit courant (`git rev-parse HEAD`) et du contenu des
  fichiers suivis modifiés localement (`git diff --name-only HEAD`), et, à part, l'empreinte des **fichiers de dépendances**
  (`package-lock.json`, `requirements*.txt`). Elle la compare au **tampon** de la dernière mise à jour réussie (fichier local,
  ignoré par git).
- Rien n'a changé → lancement direct, sans rien recompiler.
- Quelque chose a changé → écran de démarrage « Mise à jour… » qui affiche l'étape en cours, puis, dans l'ordre et seulement
  si nécessaire : installation des dépendances (**depuis le lockfile** : `npm ci`, ou `pip install -r` pour Python) si leurs
  empreintes ont changé ou si elles manquent ; migrations de la base (s'il y en a) ; compilation. Le tampon n'est écrit
  qu'après une mise à jour **entièrement** réussie.

### 8.2 Garde-fous
- **Jamais de `git pull` automatique** : seul l'utilisateur fait évoluer le dépôt.
- **Les données ne sont jamais touchées** par la mise à jour : elles vivent hors du dépôt ou dans des fichiers ignorés par
  git. Une app qui migre une base en fait d'abord une **copie de sauvegarde**.
- Réseau pendant la mise à jour : uniquement les registres de paquets (npm, PyPI), et seulement pour l'étape d'installation.
- **Échec** (réseau, compilation) : message clair en français dans l'écran de démarrage, avec le chemin du journal
  (`~/Library/Logs/<App>/mise-a-jour.log`). Si une version compilée précédente existe, l'app propose de **s'ouvrir avec
  elle** ; la compilation précédente n'est remplacée qu'après une compilation réussie. Le lancement suivant réessaie.
- Une seule mise à jour à la fois (verrou), même si l'app est lancée deux fois.
- Une modification locale non commitée compte comme un changement (l'app reflète toujours le dépôt tel qu'il est).

### 8.3 Par application

| App | Dépendances surveillées | Migrations | Compilation |
|---|---|---|---|
| Projets | `package-lock.json` | Prisma (`db:deploy`) + sauvegarde | API + interface |
| Viz | `frontend/package-lock.json`, `backend/requirements*.txt` (environnement Python de l'app) | — | interface |
| Tab | `package-lock.json` | — (fichiers JSON lus de façon tolérante) | interface + processus principal |
| Nexus | `frontend/package-lock.json`, `backend/requirements*.txt` (venv de l'app) | Alembic, au démarrage du backend | interface (export statique) |

Tab : le serveur MCP livré dans l'app (`/Applications/Atelier_Tab.app/Contents/Resources/atelier-mcp`) garde ce chemin et lance
la version du dépôt.

### 8.4 Précisions (retours des quatre implémentations)

- **Changement local** : compte tout fichier suivi modifié **et** tout fichier nouveau non ignoré par git
  (`git status --porcelain`), pas seulement `git diff`.
- **Version précédente** = la dernière compilation réussie, avec ses dépendances : une app qui lance `npm ci` met d'abord
  `node_modules` de côté et le remet en place en cas d'échec. Le code qui tourne depuis les sources (backend Python de Viz et de
  Nexus) n'a pas de version précédente : si l'installation Python échoue, l'environnement précédent est remis en place, et si
  l'app ne peut pas démarrer, l'écran le dit.
- **Base déjà migrée, compilation en échec** : la version précédente s'ouvre sur le nouveau schéma. Toute migration doit donc
  rester **compatible avec la version précédente** (ajouts seulement ; un retrait se fait en deux temps, sur deux mises à jour).
  La copie faite avant la migration permet de revenir en arrière à la main.
- **Copie avant migration** : faite seulement quand des migrations sont en attente. Si l'utilisateur a désactivé les sauvegardes,
  la migration se fait sans copie et le journal le dit.
- **Réseau** : pendant l'installation seulement, vers les registres de paquets **et** les hôtes officiels des binaires que ces
  paquets téléchargent (Electron, moteurs Prisma), sauf s'ils sont déjà en cache. Le mode « Hors ligne » d'une app ne bloque
  pas sa mise à jour (décision de l'utilisateur) ; un échec réseau propose la version précédente.
- **Lanceur à reconstruire** : une fois, ou si le dépôt change de place, **ou** (Tab) si la version d'Electron change dans le
  lockfile ; l'app le signale sur son écran de démarrage.
- **Premier lancement** : sans tampon, l'app ne sait pas si ses dépendances sont à jour ; elle fait une installation complète.
- Nexus : quand l'environnement Python doit être refait, cette étape a lieu avant l'ouverture de la fenêtre et est signalée par
  une notification macOS.
