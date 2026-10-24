# Interface — Étape 4

Next.js 16 (App Router) · Tailwind v4 · composants Shadcn (`src/components/ui/`) · Zustand.

## 1. Écran

```
┌ ⊞ [atelier_Nexus]   [agent ▾ (mobile)]          ● Data Via · 2 jeux  [Moteur ▾] [Artefacts 3] [☼] ┐
├──────────────┬─────────────────────────────────────┬──────────────────────────────────────────────┤
│ Agents       │ Conversation (streaming)            │ Artefacts (panneau droit, xl+)               │
│ par catégorie│  texte Markdown · appels d'outils   │  SQL · DAX · M · code · Markdown · données   │
│              │  repliables · liens vers artefacts  │  copier · télécharger (CSV pour les données) │
│              │ [ Écrire à … ]                      │  notes d'intégration Power BI                │
└──────────────┴─────────────────────────────────────┴──────────────────────────────────────────────┘
```

- **lg+** : barre des agents à gauche. En dessous, choix de l'agent dans l'en-tête.
- **xl+** : le panneau Artefacts s'ouvre à côté du chat dès qu'un livrable arrive. En dessous, il ne s'ouvre pas tout seul (il recouvrirait la conversation) : bouton « Artefacts » dans l'en-tête, ou clic sur le lien de l'artefact dans le fil.

## 2. Design system de la suite

- `src/styles/atelier-ds/{light,dark,colors}.css` et `src/styles/brand/` (marque, police Nunito et sa licence) : **copies verbatim** d'`Atelier_Projets/design-system` (SUITE.md §1.1). Ne jamais les modifier ici ; `designSystem.test.ts` vérifie les 6 variables de fondation, les 15 couleurs officielles et le branchement sur la charte.
- Charte « néon monochrome » : toute l'app est dans l'orange de Nexus (`#E8590C`, `data-atelier-app="nexus"` sur `<html>`). `globals.css` branche les jetons Shadcn sur les jetons `--atelier-*` de `brand/atelier-brand.css` (fond, surfaces, texte, bordures, accent, focus), qui changent seuls entre clair et sombre ; fond de page `background: var(--atelier-backdrop), var(--atelier-bg)` fixé. Cartes, panneaux, en-tête : `border-atelier-border` + `shadow-glow` ; modales et menus : `shadow-glow-strong` ; entrée active : `.atelier-nav-active`. Les statuts (`--destructive`, `--success`, `--warning`) et les séries de graphiques gardent leurs couleurs. Aucun code hex dans `globals.css`.
- Polices : pile système ; la police Nunito embarquée ne sert qu'à la marque. Aucune ressource externe (pas de Google Fonts).
- Thème : Clair / Sombre / Système (`src/components/theme/`), dans l'en-tête et dans Réglages › Apparence ; classe `dark` **et** `data-theme` sur `<html>`, clé `atelier-nexus-theme` (l'ancienne `atelier-nexus:theme` est reprise) ; script de démarrage anti-flash dans `layout.tsx`.
- Marque `atelier_Nexus` (icône Lucide `network`) + fenêtre « À propos », sélecteur « Suite Atelier » avec état des API (Nexus, Viz, Tab, Projets, Trésorerie, Ciné, Savoir) ; Atelier Cuisine, app en ligne (`online: true` dans `lib/suite.ts`), n'est jamais sondée et s'affiche « en ligne ».

## 3. Code

| Fichier | Rôle |
|---|---|
| `src/types/api.ts` | Miroirs TypeScript des schémas Pydantic |
| `src/lib/api.ts` | Client HTTP ; `streamAgent()` lit le flux SSE en POST |
| `src/lib/sse.ts` | Analyse SSE (paquets coupés, UTF-8, pings) |
| `src/features/chat-agent/conversation.ts` | Logique pure : événements d'agent → affichage + historique API |
| `src/stores/useChatStore.ts` | Agent, moteur, une conversation par agent, envoi / arrêt |
| `src/stores/useArtifactStore.ts` | **Store des artefacts** (règle CLAUDE.md) |
| `src/features/artifacts/preview.ts` | Lecture des aperçus Data Via (requête / schéma), export CSV |
| `src/features/artifacts/charts/` | Graphiques `chart` (`atelier-chart/1`) des outils d'analyse : lecture défensive, échelles, export CSV (`spec.ts`), dessin SVG avec les jetons du design system (`ChartView.tsx`) → [`analyse.md`](analyse.md) |
| `src/hooks/useBackend.ts` | Agents, moteurs, état de Data Via (rafraîchis toutes les 30 s) |
| `src/features/chains/` | Chaînes d'agents (Étape 24) : `ChainsDialog` (lancer, reprendre), `ChainBar` (étapes, validation du livrable, arrêt), `chain.ts` (logique pure, testée) ; état dans `useChainStore` |
| `src/features/chat-agent/ReviewCard.tsx` | Mode pas à pas (Étape 23) : Continuer / Corriger / Arrêter après chaque résultat ; interrupteur « Pas à pas » dans l'en-tête |
| `src/features/workflows/` | Workflows (Étape 18) : `WorkflowEditor` (enregistrer un tour, modifier un v1), `WorkflowsDialog` (liste commune v1 + v2 d'un agent ou de toute la suite, lancement v1, « Convertir » en v2), `form.ts` (logique pure, testée) |
| `src/features/workflows-graph/` | Éditeur de workflows v2 en graphe (`@xyflow/react`, contrat `docs/workflows-v2-api.md`) : `WorkflowGraphEditor` (fenêtre plein écran, ≥ 1024 px), `Palette` (catalogue par application), `StepNode`, `Inspector` (étape, condition, paramètres, formulaire généré depuis `input_schema`, menu « Utiliser… »), `RunPanel` (lancement, suivi, validation, historique). Logique pure testée : `graph.ts` (étapes ↔ nœuds/arêtes, ancêtres, ordre, couches, état d'exécution), `validate.ts`, `refs.ts` / `templates.ts` (gabarits), `schemaForm.ts`, `catalog.ts`, `draft.ts`, `run.ts` ; doubles du contrat dans `fixtures.ts` |
| `src/features/suite-map/` | Carte de la suite (`GET /api/suite/map`, `/api/suite/events`) : entrées / sorties / événements / outils / agents par app, schéma des flux, derniers événements ; `suiteMap.ts` (logique pure, testée) |
| `src/features/workflow-triggers/` | Déclencheurs (contrat `docs/declencheurs-api.md`) : `TriggersPanel` (onglet de l'éditeur : liste, formulaire horaire / événement, « Tester maintenant »), `InboxDialog` + `useInboxCount` (boîte « À valider » de l'en-tête), `OriginBadge`. Logique pure testée : `summary.ts` (résumés FR, jours consécutifs, pluriels, dates relatives), `form.ts` (brouillon ↔ corps, validation aux bornes du contrat, gabarits `{{event.…}}`, événement d'exemple), `origin.ts` (origine d'une exécution, badge) ; doubles dans `fixtures.ts` |
| `src/features/workflows-graph/ApprovalCard.tsx` | Carte de validation d'une étape (badge Lecture / Écriture / Destructif, résumé, entrée résolue, Autoriser / Refuser), avec le résultat de l'étape précédente juste au-dessus (`previousStep`, `resultExcerpt` de `run.ts`) ; partagée par le suivi et « À valider » |
| `src/features/chat-agent/ApprovalCard.tsx` | Validation dans le chat : une carte par appel (badge Lecture / Écriture / Délégation, résumé, Autoriser / Refuser), décisions envoyées ensemble ; jamais de « tout autoriser » |
| `src/lib/approval.ts`, `src/stores/useApprovalModeStore.ts` | Réglage `APPROVAL_MODE` (lu dans `GET /api/settings`, suivi à l'enregistrement des Réglages, `every_step` si illisible) et textes qui en dépendent (rappel des déclencheurs, « À valider », éditeurs) ; testés |
| `src/stores/useWorkflowStudioStore.ts` | Ouverture de la liste des workflows, de l'éditeur en graphe, de la carte et de « À valider » (une fenêtre à la fois, retour à la précédente) ; cible d'éditeur avec panneau, exécution et déclencheur prérempli |

## 4. Workflows de suite et carte

- **Points d'entrée** : bouton **Workflows** de la conversation (workflows de l'agent) ; dans l'en-tête, **Workflows**
  (tous, dont les workflows de suite `agent: null`) et **Carte** (à côté du menu des apps, masqués sous 640 px).
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
  « + » sur un événement (Viz, Projets, Tab) ouvre un nouveau workflow avec un déclencheur événement prérempli, ou
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
- **À valider** (en-tête) : badge `GET /api/workflow-runs/inbox-count` toutes les 20 s, suspendu quand l'onglet est
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

Déclencheurs et « À valider » vérifiés le 2026-10-22 dans Chromium contre un double du contrat (1440 × 900 clair et
sombre, 390 × 844, clavier), sans erreur console.

Vérifié le 2026-10-20 dans Chromium (1440 × 900 clair et sombre, 390 × 844) : liste → schéma → requête →
publication d'un DAX → réponse, sans erreur console.
