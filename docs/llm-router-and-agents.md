# LLMRouter & agents — Étape 2

Ce document décrit la couche d'orchestration LLM du backend : le format de conversation neutre, le `LLMRouter` (Claude ↔ Ollama), la classe `BaseAgent` et les endpoints associés.

## 1. Vue d'ensemble

```
API (/api/agents/…)
   │
   ▼
BaseAgent ── boucle « modèle → outils → modèle »  (app/agents/base.py)
   │   └── BaseTool.invoke()  validation Pydantic stricte  (app/tools/base.py)
   ▼
LLMRouter ── sélection du provider, repli automatique  (app/core/llm/router.py)
   │
   ├── AnthropicProvider ── SDK anthropic   (app/core/llm/providers/anthropic_provider.py)
   └── OllamaProvider ───── SDK ollama      (app/core/llm/providers/ollama_provider.py)
```

**Règle d'or** : seuls les deux modules `providers/*_provider.py` importent `anthropic` ou `ollama`. Le test `tests/test_architecture.py` fait échouer la CI en cas d'infraction.

## 2. Format neutre (`app/core/llm/types.py`)

Les agents et l'API ne manipulent que ces types ; chaque provider fait la conversion.

| Type | Rôle |
|---|---|
| `Message` | `role` (`user` / `assistant`) + liste de blocs |
| `TextBlock` | Texte |
| `ToolUseBlock` | Appel d'outil demandé par le modèle (`id`, `name`, `input`) |
| `ToolResultBlock` | Résultat renvoyé au modèle (`tool_use_id`, `tool_name`, `content`, `is_error`) |
| `ToolSpec` | Déclaration d'outil : nom, description, JSON Schema |
| `LLMRequest` / `LLMResponse` | Requête / réponse neutres, `stop_reason` normalisé |

Différences gérées par les providers :

| Sujet | Anthropic | Ollama |
|---|---|---|
| Prompt système | paramètre `system` | message `role: system` |
| Appel d'outil | bloc `tool_use` avec `id` | `tool_calls` **sans id** → le hub génère `call_xxx` |
| Résultat d'outil | bloc `tool_result` dans un message `user` | message `role: tool` + `tool_name` |
| Erreur d'outil | `is_error: true` | contenu préfixé `[ERREUR]` |
| Limite de sortie | `max_tokens` | `options.num_predict` |

## 3. LLMRouter

```python
from app.core.llm import LLMRequest, Message, get_llm_router

router = get_llm_router()
response = await router.complete(
    LLMRequest(messages=[Message.user("Bonjour")]),
    provider="ollama",          # optionnel : sinon LLM_DEFAULT_PROVIDER
)
async for event in router.stream(request):  # TextDelta…, puis ResponseComplete
    ...
```

- **Choix du provider** : par requête (`provider=`), sinon `LLM_DEFAULT_PROVIDER`.
- **Modèle** : `LLMRequest.model`, sinon `ANTHROPIC_MODEL` / `OLLAMA_MODEL`.
- **Repli** (`LLM_FALLBACK_PROVIDER`) : uniquement sur panne transitoire (réseau, timeout, 429, 5xx, surcharge) et, en streaming, seulement si aucun événement n'a encore été émis. Le nom de modèle est alors réinitialisé (non portable). Un agent qui a basculé reste sur le provider de secours jusqu'à la fin de son tour.
- **Erreurs** (`app/core/llm/errors.py`) :

| Exception | Cause | HTTP |
|---|---|---|
| `ProviderNotConfiguredError` | provider inconnu ou clé absente | 503 `provider_not_configured` |
| `ProviderUnavailableError` | panne transitoire (après repli éventuel) | 503 `provider_unavailable` |
| `ProviderRequestError` | 4xx, modèle introuvable (avec indice `ollama pull`), modèle sans support des outils | 502 `provider_request_error` |

## 4. Écrire un agent

```python
# app/agents/mon_agent.py
from typing import Any
from app.agents.base import BaseAgent
from app.agents.registry import register_agent
from app.tools import BaseTool, PublishArtifactTool

@register_agent
class MonAgent(BaseAgent):
    name = "mon_agent"                 # identifiant d'URL
    display_name = "Mon agent"
    description = "Ce que fait l'agent."
    system_prompt = "Tu es…"
    max_iterations = 8                 # garde-fou de la boucle d'outils

    def default_tools(self) -> list[BaseTool[Any]]:
        return [PublishArtifactTool()]  # déclaration explicite
```

Puis l'importer dans `app/agents/__init__.py` pour l'enregistrer.

## 5. Écrire un outil

```python
from pydantic import Field
from app.tools import BaseTool, ToolContext, ToolInput, ToolOutput

class MonInput(ToolInput):               # extra="forbid" : champs inconnus refusés
    table: str = Field(description="Nom de la table Data Via")

class MonOutil(BaseTool[MonInput]):
    name = "describe_table"
    description = "Décrit les colonnes d'une table."
    input_model = MonInput

    async def run(self, params: MonInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content="…", artifacts=[])
```

- Le JSON Schema est rendu **portable** (`portable_schema`) : `$ref`/`$defs` déroulés, titres retirés → accepté par Claude comme par Ollama. Les modèles récursifs sont refusés.
- Une entrée invalide ou une exception ne fait **jamais** planter l'agent : le modèle reçoit un `tool_result` en erreur et peut corriger son appel.
- `ToolOutput.artifacts` : livrables envoyés au panneau Artefacts (`useArtifactStore`).

Outils fournis : `current_datetime`, `publish_artifact` (types : `sql`, `dax`, `powerquery`, `python`, `react`, `code`, `markdown`, `json`, `data_preview`).

## 6. Endpoints

### `GET /api/llm/providers`
État de chaque provider.
```json
[{"name": "anthropic", "configured": true, "available": true, "is_default": true,
  "is_fallback": false, "default_model": "claude-sonnet-5-5", "models": ["…"], "error": null}]
```

### `GET /api/agents`
Agents enregistrés et leurs outils.

### `POST /api/agents/{agent_name}/run`
```json
{
  "messages": [{"role": "user", "content": [{"type": "text", "text": "Bonjour"}]}],
  "provider": "ollama",
  "model": null,
  "conversation_id": "conv-42"
}
```
Le dernier message doit être `user`. Réponse `AgentResult` : `text`, `provider`, `model`, `stop_reason` (`end_turn`, `max_tokens`, `max_iterations`…), `iterations`, `usage`, `artifacts`, `new_messages` (à ajouter à l'historique côté client pour le tour suivant).

### `POST /api/agents/{agent_name}/stream`
Même corps ; réponse **Server-Sent Events**. Champ `data` en JSON :

| `event` | `data` |
|---|---|
| `text_delta` | `{"text": "…"}` |
| `tool_call` | `{"id", "name", "input"}` |
| `artifact` | `{"artifact": {"kind", "title", "content", "language", "metadata"}}` → `useArtifactStore` |
| `tool_result` | `{"id", "name", "content", "is_error"}` |
| `done` | `{"result": AgentResult}` |
| `error` | `{"code", "message", "provider"}` |

Exemple :
```bash
curl -N -X POST localhost:8000/api/agents/assistant/stream \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":[{"type":"text","text":"Quel jour sommes-nous ?"}]}]}'
```

## 7. Configuration (`backend/.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `LLM_DEFAULT_PROVIDER` | `anthropic` | Provider par défaut |
| `LLM_FALLBACK_PROVIDER` | vide | Provider de secours |
| `ANTHROPIC_API_KEY` | vide | Sans clé : provider « non configuré » |
| `ANTHROPIC_MODEL` / `ANTHROPIC_TIMEOUT` | `claude-sonnet-5-5` / `120` | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `http://ollama:11434` en Docker |
| `OLLAMA_MODEL` / `OLLAMA_TIMEOUT` | `llama3.1:8b` / `300` | Le modèle doit supporter le *tool calling* |

## 8. Notes de compatibilité

- **SDK Anthropic ≥ 1.x** : plus de paramètre `temperature` sur `messages.create` ; le client HTTP sous-jacent est `httpx2` (et non `httpx`).
- **Ollama** : les petits modèles appellent les outils de façon moins fiable que Claude ; garder des schémas d'entrée simples et des descriptions explicites.
