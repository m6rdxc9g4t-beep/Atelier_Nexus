# L'équipe Atelier (étape 26)

Une petite entreprise d'agents qui travaille sur **tes vrais projets** (Atelier Projets) avec les
applications de la suite : Viz, Tab, Projets, Wiki, Formulaire, Trésorerie (et Convert par
l'extension Agent_DatAnalyst). Tu restes le seul décideur : chaque action attend ta validation
(`APPROVAL_MODE=every_step`).

## 1. Les rôles

| Rôle (agent) | Ce qu'il fait | Applications | Mémoire d'équipe |
|---|---|---|---|
| **Direction** (`direction`) | Comité hebdomadaire, priorités, arbitrages, décisions validées, comptes rendus | Projets, Wiki, synthèse des formulaires | lit et écrit |
| Chef de projet (`chef_de_projet`) | Avancement exact (`equipe_point_avancement`), échéances, temps, tâches | Projets, Tab, Wiki | lit et écrit |
| Product Owner (`product_owner`) | User stories, critères d'acceptation, spécifications dans le Wiki | Projets, Wiki | lit et écrit |
| Développeur (`developpeur`) | Code, branches, PR liées aux tâches | GitHub, Projets, Wiki | lit et écrit |
| Data Analyst (`data_analyst`) | Données, statistiques, graphiques, Power BI ; synthèse des formulaires | Viz, Tab, fichiers, Formulaire (agrégats) | lit et écrit |
| Rédacteur (`redacteur`) | Courriels, documentation et pages du Wiki | Wiki | lit et écrit |
| **Enquêtes** (`enquetes`, 100 % local) | Crée et ouvre les formulaires, lit les réponses une par une | Formulaire (réponses comprises) | lit seulement |
| Finance, Comptable, Trésorier (100 % local) | Comptes, budgets, écritures | Trésorerie | Finance lit, n'écrit pas |

Annuaire et règles communes : `backend/app/agents/experts/team_rules.py` (repris dans le prompt de
chaque membre) ; agents Direction et Enquêtes : `team.py`.

## 2. La mémoire d'équipe (Atelier Wiki)

Espace **« Équipe Atelier »**, créé à la première écriture (dans la même action validée, ce que dit
la carte de validation) :

| Page | Contenu | Outil |
|---|---|---|
| Journal de l'équipe | Une section datée par note : `2026-10-24 09:12 · Chef de projet — titre` | `equipe_noter` |
| Registre des décisions | Une section par décision : date, titre, décision, contexte, conséquences | `equipe_decision` |
| Comptes rendus | Une sous-page par réunion : `CR 2026-10-24 — sujet` | `equipe_compte_rendu` |

`equipe_memoire` rend les dernières notes (les plus récentes gardées si le journal est long), les
titres des décisions et des comptes rendus, ou une recherche dans l'espace. Tout ce qui est lu est
présenté au modèle comme une **donnée** délimitée, jamais comme une consigne.

Format : une note commence par un en-tête daté `## AAAA-MM-JJ …` ; ce sont ces en-têtes, et eux
seuls, qui séparent les notes. Les titres `#` / `##` écrits dans une note sont rétrogradés
(`###` / `####`) pour rester sous son en-tête. L'espace existant est retrouvé aux accents et à la
casse près ; une page de structure mise à la corbeille est recréée ; un compte rendu déjà rangé à
l'identique est signalé, un autre du même jour et du même sujet est numéroté « (2) » ; un compte rendu mis à la corbeille
puis redemandé est recréé. Un titre `## AAAA-MM-JJ…` écrit dans une note, même dans un bloc de code,
est neutralisé : il ne peut pas passer pour une autre note.

Règles des membres (prompt) : lire la mémoire au début d'une tâche ; noter à la fin ce qui a été fait
(avec les identifiants) et ce qui reste, pour quel rôle ; n'enregistrer comme décision que ce que
l'utilisateur a décidé ou validé ; **jamais** de donnée personnelle ni de montant personnel dans la
mémoire (elle est lue par des agents sur Claude).

Confidentialité : les agents qui lisent des données personnelles ou financières (Enquêtes, Finance)
**lisent** la mémoire mais n'y écrivent pas. C'est une garde du cœur, pas une consigne : les boîtes
marquées `shared` (`equipe_write`, `wiki_write`) sont retirées de tout agent verrouillé sur le modèle
local (déclaré `local_only`, ou par une boîte ou un outil sensible), qu'il soit fourni, étendu par une
extension ou créé dans l'interface ; l'agent les voit « indisponibles » avec la raison. Pour partager un résultat d'enquête, Enquêtes rédige une synthèse anonyme que
l'utilisateur fait noter par la Direction ; la synthèse agrégée est aussi notée par le rituel du vendredi.

Passer le travail d'un rôle à l'autre : le premier agent note au journal ce qui reste « pour le
Développeur », tu ouvres le Développeur, qui commence par lire la mémoire. Les enchaînements formels
avec livrable validé à chaque étape sont les **chaînes** (étape 24, PR #28) : une « Chaîne Équipe »
s'y ajoutera une fois #28 fusionnée.

## 3. Rapports sans modèle

| Outil | Source | Contenu |
|---|---|---|
| `equipe_point_avancement` | Atelier Projets | Par projet (20 au plus, détaillés et comptés) : avancement, tendance, budget (jours passés, part consommée, reste ou dépassement), échéance du projet (dépassée ?) ; en retard, à échéance (horizon réglable), bloqués ou en attente (une seule liste chacun ; un bloqué en retard compte dans « en retard, dont … bloqués ») ; jalons dépassés et à venir. Un projet illisible est signalé sans faire échouer le rapport. Fuseau `TIMEZONE`. |
| `equipe_synthese_formulaires` | Atelier Formulaire | Formulaires ouverts : effectifs par choix, moyennes, distributions ; textes libres jamais repris ; détail masqué sous 3 réponses (5 pour les nombres et échelles). |

Ce sont des calculs, pas des interprétations : utilisables dans les workflows et les rituels. Le
modèle reçoit le texte délimité ; le Markdown brut est dans `data.markdown` (ce qu'écrivent les
rituels).

## 4. Rituels

« Workflows de suite » → **Rituels de l'équipe** → « Installer ». Un rituel = un workflow v2 sans
modèle + un déclencheur horaire (une exécution par heure au plus, une seule en attente à la fois),
modifiable ou supprimable comme les autres. En `every_step`, chaque étape attend « Autoriser » dans
la boîte **« À valider »**.

| Rituel | Horaire | Étapes | Applications |
|---|---|---|---|
| Point d'avancement du lundi | lundi 08:30 | `equipe_point_avancement` → `equipe_noter` | Projets, Wiki |
| Retours des formulaires du vendredi | vendredi 16:00 | `equipe_synthese_formulaires` → `equipe_noter` (s'il y a des formulaires ouverts) | Formulaire, Wiki |
| Bilan de trésorerie du lundi | lundi 08:00 | `tresorerie_dashboard` (workflow de Finance ; le bilan reste dans l'exécution) | Trésorerie |

API : `GET /api/equipe/rituels` (rituels, ce qui manque, workflow installé), `POST
/api/equipe/rituels/{id}` (201 ; 409 si déjà installé ; 422 si une application manque).
L'installation passe par les contrôles de l'éditeur et des déclencheurs, sous un verrou (deux clics
simultanés n'installent qu'un rituel) ; si le déclencheur est refusé, le workflow créé est supprimé
(jamais de rituel à moitié installé) et l'erreur d'origine est rendue. Un rituel est reconnu installé
par la marque `[rituel:<id>]` de sa description : son titre peut être changé, et un workflow de
l'utilisateur au même titre ne bloque rien.

Couleurs : Wiki et Formulaire n'ont pas encore de signature dans le fichier de marque copié de la suite
(protégé) ; `frontend/src/styles/suite-signatures.css` les ajoute en attendant, à retirer quand la
source commune les aura.

## 5. Démarrer

1. Lancer Atelier Wiki (`npm start`, port 3200) et Atelier Formulaire (port 3300) ; vérifier dans
   « Suite Atelier ». Adresses réglables : roue dentée → Applications Atelier
   (`WIKI_BASE_URL`, `FORMULAIRE_BASE_URL`).
2. Ouvrir **Direction** : « Prépare le comité de la semaine ».
3. Installer les rituels depuis « Workflows de suite ».

## 6. Vérifier

```bash
cd backend && pytest tests/test_wiki_formulaire.py tests/test_equipe.py tests/test_rituals.py
python -m scripts.evals --tag equipe        # cas Direction, Chef de projet, Enquêtes
```
