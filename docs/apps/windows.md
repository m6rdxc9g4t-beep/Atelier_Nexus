# Windows et ouverture des apps entre elles — copie du contrat commun

Copie de la section 9 de `docs/SUITE.md` (identique dans Atelier_Viz, atelier-tab et Atelier_Projets). Ne pas l'éditer ici : la modifier dans les trois dépôts puis recopier.

## 9. Windows et ouverture des apps entre elles

Décision de l'utilisateur : **les quatre apps (Viz, Tab, Projets, Nexus) s'installent sur Windows comme sur son Mac**, avec la même
mise à jour automatique après un `git pull` (§8). Windows 10 (21H2+) et Windows 11, x64 et ARM64.

### 9.1 Installation
- Une commande PowerShell par dépôt, **sans droits d'administrateur** (installation pour l'utilisateur courant) :
  `powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1`.
  Elle vérifie les prérequis (Git, Node.js 22.12+ ou 24+, Python 3.11+ pour Viz et Nexus) et dit en français comment installer
  ce qui manque (`winget install …`), sans rien installer de système elle-même.
- Elle crée le **lanceur** (§8.1) et ses raccourcis : menu Démarrer (dossier « Atelier ») et Bureau (facultatif : `-SansBureau`),
  avec le nom affiché de l'app et son icône (`.ico` dérivé du logo, §1.6). Elle fait la première mise à jour, puis enregistre
  l'app (§9.4). Relancer la commande répare l'installation sans toucher aux données. `-Desinstaller` retire lanceur, raccourcis
  et enregistrement, jamais les données.
- Le lanceur n'ouvre **aucune fenêtre de console** visible.

### 9.2 Emplacements Windows (équivalents de macOS)

| Usage | macOS | Windows |
|---|---|---|
| Données propres à l'app (hors dépôt) | `~/Library/Application Support/<App>/` | `%APPDATA%\<App>\` |
| Journaux (`mise-a-jour.log`, …) | `~/Library/Logs/<App>/` | `%LOCALAPPDATA%\<App>\Logs\` |
| Dossier de données Tab | `~/Atelier_Tab` | `%USERPROFILE%\Atelier_Tab` |
| Données dans le dépôt (ignorées par git) | Viz `backend/data/`, Projets `backend/prisma/dev.db` | identiques |

`<App>` : `Atelier Viz`, `Atelier_Tab`, `Atelier_Projets`, `Atelier Nexus` (mêmes noms que sur macOS). Les chemins peuvent
contenir des espaces et des accents (`C:\Users\François\…`) : toujours cités, jamais découpés.

### 9.3 Mise à jour sous Windows
- Même règle que §8 ; Node/npm cherchés dans : `PATH`, `%ProgramFiles%\nodejs`, nvm-windows (`%NVM_SYMLINK%`), Volta, fnm,
  `%LOCALAPPDATA%\Programs\nodejs` ; Python par `py -3` puis `python`.
- **Fins de ligne** : chaque dépôt a un `.gitattributes` (`* text=auto eol=lf`, scripts `.ps1`/`.cmd` en `eol=crlf`, binaires
  en `binary`) pour qu'un clone Windows ne paraisse jamais « modifié » (sinon §8 recompilerait à chaque lancement).
- Un fichier ouvert par une app en cours d'exécution ne peut pas être remplacé sous Windows : les remplacements de §8 (dossier
  de compilation, `node_modules`) se font quand l'app n'utilise pas encore ces fichiers, sinon au lancement suivant.

### 9.4 Ouvrir une autre app de la suite
- **Environnement propre** : une app qui en ouvre une autre (sélecteur « Suite Atelier », §3) ne lui transmet **aucune** de ses
  variables (`DATABASE_URL`, `PORT`, `NEXUS_*`, `ATELIER_*`, `ELECTRON_*`, `PYTHON*`…) : seul un environnement minimal
  (utilisateur, dossier personnel, langue, fuseau, `PATH` système) passe. Chaque app, de son côté, **ignore** toute variable
  héritée qui désignerait autre chose que ses propres données (ex. Projets ignore un `DATABASE_URL` hérité au lancement de
  l'app de bureau).
- macOS : `open -b <identifiant>` (inchangé). Windows : chaque app installée s'enregistre dans
  `HKCU\Software\Atelier\Apps\<viz|tab|projets|nexus>` (valeurs `Lanceur` = chemin complet, `Nom`) ; les autres apps y lisent le
  lanceur et le démarrent, sinon ouvrent l'adresse (§2) dans le navigateur par défaut.

### 9.5 Vérification
Chaque dépôt ajoute à sa CI un travail `windows-latest` : tests, compilation, puis `install.ps1` dans un profil temporaire
(sans raccourci de Bureau) et un lancement du lanceur en mode « mise à jour seulement » qui doit réussir, puis un second
lancement qui ne doit **rien** refaire (vérifie §9.3 fins de ligne).
