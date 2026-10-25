# Interface — Étape 4

Next.js 16 (App Router) · Tailwind v4 · composants Shadcn (`src/components/ui/`) · Zustand.

## 1. Écran

Refonte visuelle (étape 24) : « cockpit d'agents », calme par défaut, néon sur l'intention.

```
┌ Barre latérale (lg+) ─────┬ Accueil · Conversation · Studio des workflows ─────┬ Livrables (xl+) ┐
│ ⊞ [▣] atelier_Nexus        │ ▣ Agent · badges            [Workflows][Historique] │ liste · type    │
│ ⌂ Accueil                  │                                                      │ copier          │
│ ⟿ Workflows                │  réponses (tuile de l'agent) · actions regroupées   │ télécharger     │
│ ◫ Carte de la suite        │  en une ligne d'activité · carte « Votre accord     │ notes Power BI  │
│ ✓ À valider (n)            │  est nécessaire » · dock de décision                │                 │
│ AGENTS  [Rechercher /]     │                                                      │                 │
│ ▾ Général …                │  [ Écrire à … ] [📎] [moteur ▾]   Entrée · Maj+Entrée │                 │
│ ● Apps 3/9  ☼☾▣  ⚙         │                                                      │                 │
└────────────────────────────┴──────────────────────────────────────────────────────┴─────────────────┘
```

- **Barre latérale unique** (`components/layout/AppSidebar.tsx`, fixe ≥ lg, en tiroir `Sheet` sous lg) : sélecteur
  Suite Atelier et marque, navigation (Accueil, Workflows, Carte de la suite, À valider avec son badge), agents
  (`AgentSidebar` : recherche sans accents, « / » ou ⌘K / Ctrl+K pour y aller, catégories repliables mémorisées,
  tuile de chaque agent, crayon des agents personnalisés), puis état des applications, thème et Réglages.
- **Barre mobile** (`AppHeader`, sous lg) : marque, bouton du contexte courant (accueil, onglet du Studio ou agent,
  `headerContext.ts`) qui ouvre le tiroir, « À valider » et la Suite. Sous lg, l'en-tête de la conversation ne garde
  que les badges et les actions.
- **Vues** (`stores/useNavStore.ts`) : `home` (accueil) ou `agents` (conversation). Le **Studio des workflows**
  remplace la vue tant que `listOpen`, `mapOpen` ou `inboxOpen` est vrai (`useWorkflowStudioStore`, API inchangée,
  `closeStudio()` pour revenir) ; l'éditeur en graphe reste une fenêtre plein écran par-dessus.
- **Accueil** (`features/home/`) : question rapide à l'Assistant (nouvelle conversation), « Reprendre » (conversations
  récentes, `GET /api/conversations?limit=`), agents mis en avant (premier de chaque catégorie, puces des applications
  qu'ils utilisent), état de la suite, « À valider », 3 modèles de workflows de suite (disponibles d'abord).
- **Livrables** (ex-Artefacts) : en xl (≥ 1280 px), colonne à droite du chat avec « Agrandir » (60 % de la largeur) ;
  en dessous, tiroir modal à droite (voile, Échap, focus piégé et rendu). Liste des livrables au lieu d'un menu,
  filtre « Conversations / Workflows » (préfixe `workflow:`) quand les deux existent, précédent / suivant, « Retirer
  du panneau » avec confirmation (rien n'est supprimé côté serveur).

## 2. Design system de la suite

- `src/styles/atelier-ds/{light,dark,colors}.css` et `src/styles/brand/` (marque, police Nunito et sa licence) : **copies verbatim** d'`Atelier_Projets/design-system` (SUITE.md §1.1). Ne jamais les modifier ici ; `designSystem.test.ts` vérifie les 6 variables de fondation, les 15 couleurs officielles et le branchement sur la charte.
- Charte « néon monochrome » : toute l'app est dans l'orange de Nexus (`#E8590C`, `data-atelier-app="nexus"` sur `<html>`). `globals.css` branche les jetons Shadcn sur les jetons `--atelier-*` de `brand/atelier-brand.css` (fond, surfaces, texte, bordures, accent, focus), qui changent seuls entre clair et sombre ; fond de page `background: var(--atelier-backdrop), var(--atelier-bg)` fixé. Aucun code hex dans `globals.css`.
- **Règle d'élévation** : surface calme par défaut (`bg-card border border-atelier-line`, sans halo) ; interactif au
  survol (`hover:border-atelier-border hover:shadow-glow`) ; mis en avant, actif ou vivant (élément sélectionné,
  bouton principal, réponse en cours, validation attendue) : `border-atelier-border shadow-glow` ; superposé
  (fenêtres, menus, tiroirs) : `shadow-glow-strong` ; creusé (JSON, journaux, code) : `bg-sunken`. Entrée active :
  `.atelier-nav-active`. Séparateurs de structure : `border-atelier-line`.
- **Encres de statut** : `text-warning-ink`, `text-success-ink`, `text-destructive-ink` (couleur du statut mêlée au
  texte, ≥ 4,5:1 en clair comme en sombre) pour tout texte ; les icônes et pastilles gardent `text-warning`… Les
  statuts (`--destructive`, `--success`, `--warning`) et les séries de graphiques gardent leurs couleurs.
- **Identité** : `AgentTile` (tuile d'un agent, verre néon ou discrète), `AppChip` (puce d'une application dans SA
  couleur par `appTheme` : `data-atelier-app`, ou signature locale pour Convert `#C9951D` que la marque copiée ne
  connaît pas), `agentApps()` (applications d'un agent d'après ses boîtes).
- **Primitives** (`src/components/ui/`) : `card`, `callout` (info, signature, warning, destructive, success, avec
  action), `decision-card` (anatomie unique des validations : conversation, éditeur, « À valider »), `skeleton`,
  `segmented`, `kbd`, `status-dot`, `section-label`, `empty-state`, `sheet` (côté `left` ou `right`), `dialog` (props
  `size` sm | md | lg | xl et `scroll="body"` avec `DialogBody`), `badge` (variante `signature`), `button`
  (variante `soft`, taille `icon-xs`).
- Polices : pile système ; la police Nunito embarquée ne sert qu'à la marque (SUITE.md §1.6), y compris pour les
  titres. Aucune ressource externe (pas de Google Fonts).
- Thème : Clair / Sombre / Système (`src/components/theme/`), en bas de la barre latérale et dans Réglages › Apparence ; classe `dark` **et** `data-theme` sur `<html>`, clé `atelier-nexus-theme` (l'ancienne `atelier-nexus:theme` est reprise) ; script de démarrage anti-flash dans `layout.tsx`.
- Marque `atelier_Nexus` (icône Lucide `network`) + fenêtre « À propos » (logo complet `public/brand/logo-atelier-nexus.png`, classe `.atelier-about__logo`), sélecteur « Suite Atelier » avec état des API (Nexus, Viz, Tab, Projets, Convert, Trésorerie, Ciné, Savoir) ; Atelier Cuisine, app en ligne (`online: true` dans `lib/suite.ts`), n'est jamais sondée et s'affiche « en ligne ».
- Réglages ouvrables de partout (`stores/useUiStore.ts`, `openSettings()`) : bouton de la barre latérale, messages
  « non configuré » de la conversation.

## 3. Code

| Fichier | Rôle |
|---|---|
| `src/types/api.ts` | Miroirs TypeScript des schémas Pydantic |
| `src/lib/api.ts` | Client HTTP ; `streamAgent()` lit le flux SSE en POST |
| `src/lib/sse.ts` | Analyse SSE (paquets coupés, UTF-8, pings) |
| `src/features/chat-agent/conversation.ts` | Logique pure : événements d'agent → affichage + historique API |
| `src/stores/useChatStore.ts` | Agent, moteur, une conversation par agent, envoi / arrêt |
| `src/stores/useArtifactStore.ts` | **Store des artefacts** (règle CLAUDE.md), affiché dans le panneau Livrables |
| `src/features/artifacts/preview.ts`, `panel.ts` | Lecture des aperçus Data Via (requête / schéma) ; logique du panneau Livrables (provenance conversation / workflow, filtre, voisins, sélection après retrait, nom de fichier, export CSV, `KIND_LABELS`) ; testés |
| `src/features/chat-agent/thread.ts` | Fil de la conversation : actions consécutives regroupées en une ligne d'activité (`groupParts`, `activitySummary`), paramètres lisibles d'une validation (`formatParams`, sans injection de ligne), annonces `aria-live` (`liveMessage`) ; testé |
| `src/features/chat-agent/agentList.ts`, `agentApps.ts`, `src/lib/labels.ts` | Recherche et catégories de la barre des agents ; applications d'un agent ; noms des moteurs et moteur effectif (source unique) ; testés |
| `src/features/home/home.ts` | Accueil : salutation, agents mis en avant, résumé de l'état de la suite ; testé |
| `src/stores/useNavStore.ts`, `src/stores/useUiStore.ts` | Vue affichée (accueil / conversation) et tiroir mobile ; fenêtre des Réglages ouvrable de partout |
| `src/hooks/useBackend.ts` | Agents, moteurs, état de Data Via (rafraîchis toutes les 30 s) |
| `src/features/workflows/` | Workflows (Étapes 18 et 24) : `WorkflowsStudio` (vue plein cadre : onglets Workflows — « Mes workflows » / « Modèles de la suite » —, Carte de la suite, À valider), `WorkflowsDialog.tsx` (bouton Workflows de la conversation et `MyWorkflows` : cartes avec chaîne d'applications, lancement v1, « Passer en graphe », badge « Simple » pour un v1), `TemplateGallery` (modèles de `GET /api/workflows/library`, disponibilité, prérequis repliés, « Utiliser ce modèle »), `WorkflowEditor` (enregistrer un tour, modifier un v1). Logique pure testée : `form.ts`, `chain.ts` (chaîne d'applications d'un workflow), `studio.ts` (onglet, filtres, modèles mis en avant, `missingLines`, cible « Utiliser ce modèle ») |
| `src/features/workflows-graph/` | Éditeur de workflows v2 en graphe (`@xyflow/react`, contrat `docs/workflows-v2-api.md`) : `WorkflowGraphEditor` (fenêtre plein écran, ≥ 1024 px), `Palette` (catalogue par application), `StepNode`, `Inspector` (étape, condition, paramètres, formulaire généré depuis `input_schema`, menu « Utiliser… »), `RunPanel` (lancement, suivi, validation, historique). Logique pure testée : `graph.ts` (étapes ↔ nœuds/arêtes, ancêtres, ordre, couches, état d'exécution), `validate.ts`, `refs.ts` / `templates.ts` (gabarits), `schemaForm.ts`, `catalog.ts`, `draft.ts` (dont `draftFromTemplate` : copie non enregistrée d'un modèle, `saveState`), `run.ts`, `leave.ts` (quitter l'éditeur vers la liste ou les modèles) ; doubles du contrat dans `fixtures.ts` |
| `src/features/suite-map/` | Carte de la suite (`GET /api/suite/map`, `/api/suite/events`) : entrées / sorties / événements / outils / agents par app, schéma des flux, derniers événements ; `suiteMap.ts` (logique pure, testée) |
| `src/features/workflow-triggers/` | Déclencheurs (contrat `docs/declencheurs-api.md`) : `TriggersPanel` (onglet de l'éditeur : liste, formulaire horaire / événement, « Tester maintenant »), `InboxDialog.tsx` (`InboxButton` de la barre mobile, `InboxView` de l'onglet « À valider »), `useInboxCount` + `sharedPoll.ts` (une seule lecture partagée par tous les badges), `OriginBadge`. Logique pure testée : `summary.ts` (résumés FR, jours consécutifs, pluriels, dates relatives), `form.ts` (brouillon ↔ corps, validation aux bornes du contrat, gabarits `{{event.…}}`, événement d'exemple), `origin.ts` (origine d'une exécution, badge) ; doubles dans `fixtures.ts` |
| `src/features/workflows-graph/ApprovalCard.tsx` | Carte de validation d'une étape (`DecisionCard` : badge Lecture / Écriture / Destructif, résumé, entrée résolue sous « Détails », Refuser / Autoriser), avec le résultat de l'étape précédente juste au-dessus (`previousStep`, `resultExcerpt` de `run.ts`) ; partagée par le suivi et « À valider » |
| `src/features/chat-agent/ApprovalCard.tsx`, `DecisionDock` | Validation dans le chat (`DecisionCard`) : une ligne par appel (nature, application, paramètres sous « Détails », Refuser / Autoriser), « Envoyer mes choix » pour plusieurs appels, reçu après décision ; dock « L'agent attend votre accord · Voir » au-dessus du composer quand la carte est hors de vue (il n'autorise jamais) ; jamais de « tout autoriser » |
| `src/lib/approval.ts`, `src/stores/useApprovalModeStore.ts` | Réglage `APPROVAL_MODE` (lu dans `GET /api/settings`, suivi à l'enregistrement des Réglages, `every_step` si illisible) et textes qui en dépendent (rappel des déclencheurs, « À valider », éditeurs) ; testés |
| `src/stores/useWorkflowStudioStore.ts` | Onglet du Studio (liste, carte, « À valider » : un à la fois, retour au précédent après l'éditeur ; `listSection` « mine » / « templates », `openTemplates()`, `closeStudio()`) et éditeur en graphe ; cible d'éditeur avec panneau, exécution, déclencheur prérempli ou modèle (`template`) |

## 4. Workflows de suite et carte

- **Points d'entrée** : bouton **Workflows** de la conversation (workflows de l'agent) ; dans la barre latérale,
  **Workflows** (tous, dont les workflows de suite `agent: null`, et les modèles de la suite), **Carte de la suite**
  et **À valider** ; sur l'accueil, trois modèles et « Voir tous les modèles ».
- **Modèles de la suite** : « Utiliser ce modèle » ouvre l'éditeur sur une copie **non enregistrée** du modèle
  (`openEditor({ kind: "new", agent: null, template })`, `draftFromTemplate`) ; rien n'est lancé, et chaque étape
  attend la validation à l'exécution. Un modèle indisponible s'ouvre quand même (l'éditeur signale ce qui manque).
  `GET /api/workflows/library` en 404 = serveur sans modèles (message d'information).
- **Éditeur en graphe** : palette à gauche (glisser-déposer ou « + », ajouté après l'étape sélectionnée), graphe au
  centre (poignée de sortie → poignée d'entrée = `needs` ; Suppr / Retour arrière supprime nœud ou liaison ; liaison
  qui ferait une boucle refusée), inspecteur à droite (onglets Étape / Workflow et Exécution). Les erreurs locales
  (cycle, identifiant, référence non ancêtre, paramètre non déclaré…) s'affichent tout de suite ; **Valider** ajoute
  celles du serveur (`INPUT_INVALID` sur le champ concerné). « Utiliser… » ne propose que les paramètres et les étapes
  **ancêtres** (`{{steps.id.data}}`, `.content`, `.status`, et pour une table `atelier-table/1` annoncée :
  `.data.rows[0].<colonne>`, `.data.total`). Fermer avec des modifications non enregistrées demande confirmation.
- **Exécution** : enregistre (et valide) si besoin, lance, interroge `GET /api/workflow-runs/{id}` tant que
  `running` (500 ms puis jusqu'à 3 s) ; `awaiting_approval` → carte Autoriser / Refuser avec l'entrée résolue
  (`resume`) ; statuts sur les nœuds ; livrables dans `useArtifactStore` (agent `workflow:<id>`) ; historique cliquable.
- **Carte de la suite** : « + » sur une action ouvre un nouveau workflow de suite qui commence par `node:<app>/<action>` ;
  « + » sur un événement (Viz, Projets, Tab, Convert) ouvre un nouveau workflow avec un déclencheur événement prérempli, ou
  l'ajoute au dernier workflow ouvert dans l'éditeur.

## 4 bis. Déclencheurs et « À valider »

- **Onglet Déclencheurs** de l'éditeur (à côté de Workflow et Exécution) : un déclencheur lance la version
  **enregistrée** d'un workflow v2 ; tant que le workflow n'est pas enregistré, l'onglet propose de l'enregistrer
  (un déclencheur prérempli attend l'enregistrement) ; un v1 doit d'abord être converti.
- **Liste** : libellé, résumé (« Chaque jour à 08:00, du lundi au vendredi » ; « Quand Projets publie *Statut changé*
  et data.to = CLOSED »), interrupteur actif / coupé (le corps est renvoyé tel quel), prochaine occurrence, dernière
  exécution et son suivi, compteurs, garde-fous, `last_error` et `warning` en bandeau. Relue toutes les 30 s quand
  l'onglet est visible.
- **Formulaire** : horaire (intervalle 5 à 1440 min, ou heure `HH:MM` en 24 h et jours, « ouvrés » / « tous ») ;
  événement depuis `GET /api/triggers/events-catalog` (app dans sa couleur avec son état, types cochés, filtres :
  champ proposé depuis `fields`, opérateur, valeur ; « fait partie de » = valeurs séparées par des virgules ;
  anti-rafale 0 à 3600 s) ; paramètres du workflow (vide = défaut, seuls les paramètres modifiés sont envoyés) avec
  « Utiliser… » qui insère `{{event.subject.id}}`, `{{event.data.<champ>}}`… ; plafond 1 à 120 par heure. Erreurs
  locales sous chaque champ après la première tentative ; le serveur reste l'autorité (422 affiché tel quel).
- **Tester maintenant** : un horaire part tel quel ; un événement part avec un exemple prérempli depuis le
  catalogue (il respecte les filtres d'égalité), modifiable en JSON. Le résultat s'ouvre dans l'onglet Exécution.
- **À valider** (barre latérale, onglet du Studio) : badge `GET /api/workflow-runs/inbox-count` toutes les 20 s, suspendu quand l'onglet est
  caché, relu après chaque décision ; fenêtre des exécutions `awaiting_approval` de tous les workflows (titre,
  origine « Déclenché par projets.work_item.status_changed · Écrire la doc », ancienneté) avec la carte de
  validation de l'éditeur (résultat de l'étape précédente au-dessus), et « Ouvrir dans l'éditeur » (suivi de cette
  exécution). Textes selon `APPROVAL_MODE` : « avant chaque étape » (défaut) ou « avant chaque écriture ».
- **Historique** : chaque exécution porte son origine (Manuel, Horaire, Événement, Test) et son événement source.
- Hypothèses au-delà du contrat : `trigger_id` / `trigger_event` lus comme facultatifs (exécutions d'avant la
  migration) ; un type d'événement inconnu n'est signalé localement que si l'app du catalogue liste des événements.

## 5. Historique des conversations

Historique : le client renvoie l'historique complet à chaque tour et y ajoute les `new_messages` de l'événement `done`. En cas d'erreur ou d'arrêt, la question sans réponse reste affichée mais sort de l'historique, pour pouvoir continuer.

## 6. Vérifier

```bash
cd frontend
npm run lint && npm run typecheck && npm test && npm run build
```

Démonstration complète **sans clé Claude ni Ollama** (moteur scripté, vrais outils Data Via) :

```bash
# 1. Atelier Viz avec ses données d'exemple (port 8000)
# 2. Backend de démonstration (port 8100)
cd backend && python -m scripts.demo_server
# 3. Interface
cd frontend && npm run dev        # http://localhost:3100 → agent « Démo Data Via »
```

Refonte visuelle vérifiée le 2026-10-25 dans Chromium (1440 × 900 clair et sombre, 375 × 812) : accueil, barre
latérale et tiroir, Studio (mes workflows, modèles, carte), modèle copié dans l'éditeur, conversation avec le
serveur de démonstration (carte de validation, ligne d'activité, suggestion « Rejouer ces actions »).

Déclencheurs et « À valider » vérifiés le 2026-10-22 dans Chromium contre un double du contrat (1440 × 900 clair et
sombre, 390 × 844, clavier), sans erreur console.

Vérifié le 2026-10-20 dans Chromium (1440 × 900 clair et sombre, 390 × 844) : liste → schéma → requête →
publication d'un DAX → réponse, sans erreur console.
