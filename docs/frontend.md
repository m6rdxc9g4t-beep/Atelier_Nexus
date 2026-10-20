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
| `src/hooks/useBackend.ts` | Agents, moteurs, état de Data Via (rafraîchis toutes les 30 s) |

Historique : le client renvoie l'historique complet à chaque tour et y ajoute les `new_messages` de l'événement `done`. En cas d'erreur ou d'arrêt, la question sans réponse reste affichée mais sort de l'historique, pour pouvoir continuer.

## 4. Vérifier

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

Vérifié le 2026-10-20 dans Chromium (1440 × 900 clair et sombre, 390 × 844) : liste → schéma → requête →
publication d'un DAX → réponse, sans erreur console.
