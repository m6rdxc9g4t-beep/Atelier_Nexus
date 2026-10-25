# Connecteur Atelier Tab (étapes 7, 8 et 10)

Atelier Tab (tableur + base typée) **n'a pas d'API HTTP**. L'app de bureau publie chaque table, à chaque
enregistrement, dans `~/Atelier_Tab/exports/<id de table>.json` : une enveloppe **DataFlow v2.1.0** avec les
valeurs calculées par son moteur de formules. Nexus lit ces fichiers, en lecture seule, comme le fait Atelier Viz.

Code : `backend/app/tools/tab.py` (lecteur `TabSnapshots` et outils), schémas `backend/app/schemas/tab.py`.
Contrat de référence : `atelier-tab/src/dataflow/schema/atelier.v2_1.ts` et `docs/DATAFLOW_SPEC.md`.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `TAB_EXPORTS_DIR` | `~/Atelier_Tab/exports` | Dossier des instantanés (vide = connecteur désactivé). Suit `ATELIER_TAB_DATA` de Tab : `<dossier de données>/exports`. |
| `TAB_MAX_SNAPSHOT_MB` | `50` | Taille maximale lue par fichier |

Le mode navigateur de Tab (`npm run dev`, ports 5175 / 4175) garde ses données dans IndexedDB : rien n'arrive sur
le disque. Ouvrez l'**app de bureau** au moins une fois.

Docker : le `docker-compose.yml` monte `${HOME}/Atelier_Tab/exports` en lecture seule dans le conteneur backend
(`/data/atelier_tab_exports`).

## Lecture des fichiers

- Seuls les `*.json` au nom sûr sont lus ; un lien symbolique qui sort du dossier est ignoré ; un fichier trop gros
  est signalé, jamais chargé ; un fichier illisible (en cours d'écriture, autre format, version ≠ `2.1.0`) est ignoré.
- **Instantané ou export manuel** : les exports manuels (`atelier_projets_<projet>_<date>.json`) sont rangés dans
  le même dossier. Pour une même table (`project.source_table.id`), l'instantané (nom de fichier = id de la table)
  l'emporte ; à défaut, l'export le plus récent, marqué « export manuel ».
- Les valeurs utilisées sont `computed`. Les lignes de total (`summary_rows`) sont affichées à part et **exclues**
  des calculs. Les erreurs de formule (`#DIV/0!`, `#REF!`…) sont ignorées dans les calculs et signalées.
- Les pourcentages sont des fractions sur le fil (`0.2`) et affichés « 20 % ».
- Les identifiants stables sont `columns_schema[].id` et `record_id` : la lettre de colonne et le numéro de ligne
  changent quand on insère des colonnes ou des lignes.

## Outils (boîte `tab`, lecture seule)

| Outil | Rôle |
|---|---|
| `tab_list_tables` | Tables disponibles : espace › projet › table, lignes, colonnes, date, source |
| `tab_read_table` | Colonnes (type, rôle DataFlow) et lignes paginées (`offset`, `limit` ≤ 200), colonnes choisies par libellé, id ou lettre ; artefact `data_preview` complet si la table dépasse la page |
| `tab_aggregate` | Somme, moyenne, min, max, nombre ; regroupement par une colonne ; filtres d'égalité |
| `tab_check_table` | Erreurs de formule, titres vides ou en double, échéances dépassées non terminées (`as_of`, sinon le jour courant dans le fuseau `TIMEZONE`, Europe/Paris par défaut : à 0 h 30 à Paris, c'est déjà le lendemain même si UTC est encore la veille), responsables manquants, préparation à l'import dans Atelier Projets |

## Écriture par le serveur MCP de Tab (étape 8, boîte `tab_write`)

Tab expose ses outils de données par un serveur **MCP en stdio** (`desktop/mcp-server.ts`), qui utilise le même
store et le même moteur de formules que l'application. Nexus le lance à la première écriture d'un tour d'agent,
lui parle en JSON-RPC (une ligne par message : `initialize`, `notifications/initialized`, `tools/call`), puis
l'arrête à la fin du tour. À chaque appel, le serveur relit le dossier de données, applique l'outil, écrit les seuls
fichiers modifiés et **met à jour l'instantané** : `tab_read_table` voit le changement aussitôt. Si l'app est
ouverte, elle se recharge d'elle-même.

Code : `backend/app/tools/tab_mcp.py` (client `TabMcpClient` et outils). Tests : `tests/test_tab_write.py`, avec un
faux serveur lancé en vrai sous-processus (`tests/fake_tab_mcp.py`).

| Variable | Défaut | Rôle |
|---|---|---|
| `TAB_MCP_COMMAND` | vide (lecture seule) | App Mac : `/Applications/Atelier_Tab.app/Contents/Resources/atelier-mcp`. Dépôt : `node <atelier-tab>/dist-desktop/atelier-mcp.mjs` après `npm run build:desktop`. Windows : chemin entre guillemets s'il contient des espaces (`"C:\Program Files\nodejs\node.exe" "C:\…\atelier-tab\dist-desktop\atelier-mcp.mjs"`) ; l'app de bureau prend d'elle-même `%LOCALAPPDATA%\Programs\Atelier_Tab\resources\atelier-mcp.cmd` s'il existe (SUITE.md §9.6). Un script `.cmd` est lancé sans console ; ses arguments viennent de ce réglage, jamais des données (entrée standard). |
| `TAB_DATA_DIR` | vide (`~/Atelier_Tab`) | Dossier de données transmis au serveur (`ATELIER_TAB_DATA`). Si vous le changez, `TAB_EXPORTS_DIR` = `<ce dossier>/exports`. |
| `TAB_MCP_TIMEOUT` | `30` | Délai d'un appel (s) |

| Outil | Rôle | Outil de Tab |
|---|---|---|
| `tab_set_cells` | Modifier jusqu'à 100 cellules (ligne par numéro ou `rec_…`, colonne par lettre, libellé ou id) | `set_cells` |
| `tab_add_rows` | Ajouter des lignes `{colonne: valeur}`, au-dessus de la ligne de total par défaut | `add_rows` |
| `tab_delete_rows` | Supprimer des lignes (formules ajustées comme dans Excel), **titre de chaque ligne vérifié juste avant** | `read_table` puis `delete_rows` |
| `tab_add_column` | Ajouter une colonne typée ; formule de la ligne 1 recopiée ; préréglage « Statuts Atelier » | `add_column` |
| `tab_create_table` | Créer une table dans un projet, avec ses colonnes et leurs rôles DataFlow | `create_table` |

- **Toutes soumises à validation**, avec un résumé lisible (« Ajouter 1 ligne(s) à la table tbl_planning_lots :
  « Plomberie » »).
- **Suppression vérifiée** : `tab_delete_rows` demande, pour chaque ligne (`rows` : numéro ou `rec_…`), son titre
  attendu (`titles`, même ordre, tel que lu par `tab_read_table`). La carte de validation montre ces titres
  (« Supprimer définitivement 2 ligne(s) de la table tbl_a : « Plomberie » (ligne 3), « Peinture » (rec_9) »). Juste
  avant de supprimer, l'outil relit la table **par le serveur MCP** (même store que l'app, aucun retard d'instantané)
  et refuse tout si une ligne n'existe plus ou ne contient plus son titre (casse, accents et espaces ignorés ; un
  titre recopié tronqué « … » vaut pour son début s'il en garde au moins 4 caractères). Une ligne entièrement vide se désigne par un titre vide `""`
  (carte : « ligne vide ») ; ce titre ne supprime jamais une ligne qui contient une valeur. Une même ligne citée par
  son numéro et par son `rec_…` est refusée. La suppression part ensuite par identifiant stable (`rec_…`) : une ligne
  ajoutée ou supprimée entre-temps ne décale plus la cible.
- Les valeurs s'écrivent comme une saisie dans la grille (« 12 000 », « 15/01/2027 », libellé du statut, nom du
  responsable, `=C5*1.2`) : c'est Tab qui les interprète.
- Les entrées sont validées avant tout lancement du serveur (identifiant de table, formule obligatoire pour une
  colonne formula…). Les refus de Tab (table ou colonne introuvable) reviennent tels quels à l'agent.
- **Environnement minimal** : le serveur ne reçoit que `PATH`, `HOME`, la langue et `ATELIER_TAB_DATA`, jamais les
  clés ni les secrets de Nexus.
- Non exposés : renommage, suppression de colonne, configuration et lancement des exports vers Atelier Projets.
- Docker : l'image du backend n'a pas Node ni l'app Tab ; pour écrire dans Tab, lancez le backend Nexus sur la
  machine.

## Envoyer une table dans Atelier Projets (étape 10, boîte `tab_projets`)

Le pont DataFlow de la suite (`docs/SUITE.md` §4) : une table de Tab devient des éléments de Projets. Nexus lit
l'enveloppe **telle que Tab l'a publiée** (aucune réécriture) et l'envoie à l'import d'Atelier Projets.

| Outil | Rôle |
|---|---|
| `projets_preview_tab_import` | `POST /api/imports/atelier-tab/preview` : projet, phase, epic et story cibles (existants ou à créer), éléments créés / mis à jour / inchangés / ignorés avec la raison, avertissements. **Ne modifie rien.** |
| `projets_import_tab_table` | `POST /api/imports/atelier-tab` : **validation**. Clé `Idempotency-Key` = empreinte de l'enveloppe et des options : rejouer le même import ne crée rien (Nexus le signale) ; après une modification dans Tab, le réimport met à jour les éléments existants (rattachés par `record_id`). |

Options : `project_id` (sinon le projet du même nom, créé au besoin), `type` (TASK par défaut), `rows` (numéros ou
`rec_…` ; compteurs et totaux recalculés comme Tab, lignes de total exclues).

En-têtes : `X-Atelier-Schema-Version: 2.1.0` et, si Projets protège l'import (`ATELIER_IMPORT_TOKEN`),
`Authorization: Bearer` avec la valeur de `PROJETS_IMPORT_TOKEN` côté Nexus.

Code : `backend/app/tools/tab_projets.py` (outils), `ProjetsClient.preview_tab_import` / `import_tab`
(`app/tools/projets.py`), `TabSnapshots.envelope_json` (`app/tools/tab.py`). Tests : `tests/test_tab_projets.py`.

## Agents

- **Tableur** (`tableur`) : `core`, `tab`, `tab_write`, `tab_projets`.
- **Chef de projet** (`chef_de_projet`) : `tab` et `tab_projets` en plus de Projets.
- **Data Analyst / Power BI** et **Chef de projet** ont aussi la boîte `tab`.
