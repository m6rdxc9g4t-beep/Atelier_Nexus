# Connecteur Atelier Tab (Étape 7)

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
| `tab_check_table` | Erreurs de formule, titres vides ou en double, échéances dépassées non terminées (`as_of`), responsables manquants, préparation à l'import dans Atelier Projets |

Écrire dans Tab passe par son serveur MCP (`desktop/mcp-server.ts`) : hors du périmètre de cette étape.

## Agents

- **Tableur** (`tableur`) : `core`, `tab`.
- **Data Analyst / Power BI** et **Chef de projet** ont aussi la boîte `tab`.
