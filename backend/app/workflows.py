"""Workflows rejouables : capture d'un tour d'agent et exécution sans modèle.

- **Capture** : les appels d'outils réussis du dernier tour d'une conversation deviennent les
  étapes d'un workflow (les appels en erreur, refusés ou non rejouables sont écartés).
- **Exécution** : les étapes sont vérifiées toutes avant de commencer (outil disponible,
  paramètres valides), les écritures attendent la validation de l'utilisateur comme dans le
  chat, puis les outils s'exécutent dans l'ordre avec un contexte partagé (l'exploration
  préalable de Data Via reste satisfaite). La première erreur arrête tout (porte de contrôle).

Aucun modèle n'intervient : rien ne quitte la machine, même pour un agent « 100 % local ».
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.agents.base import BaseAgent
from app.core.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.schemas.workflows import (
    PLACEHOLDER,
    PendingStep,
    SkippedCall,
    StepResult,
    WorkflowDraft,
    WorkflowParam,
    WorkflowRunResult,
    WorkflowStep,
)
from app.tools.base import Artifact, ToolContext

#: Outils jamais rejoués : ils n'ont de sens qu'avec un modèle
NOT_REPLAYABLE = {
    "delegate_to_agent": "confie le travail à un autre agent, donc à un modèle",
    "current_datetime": "n'apporte rien sans modèle pour lire la date",
}
MAX_CONTENT = 4000


class WorkflowError(ValueError):
    """Workflow impossible à capturer ou à lancer (message lisible)."""


# ─── Capture ──────────────────────────────────────────────────────


def _is_question(message: Message) -> bool:
    return message.role == "user" and any(
        not isinstance(b, ToolResultBlock) for b in message.content
    )


def last_turn(messages: Sequence[Message]) -> tuple[str, list[Message]]:
    """(texte de la dernière question, messages du tour qui y répond)."""
    for index in range(len(messages) - 1, -1, -1):
        if _is_question(messages[index]):
            question = " ".join(
                b.text for b in messages[index].content if isinstance(b, TextBlock)
            ).strip()
            return question, list(messages[index + 1 :])
    return "", list(messages)


def capture(agent: BaseAgent, messages: Sequence[Message]) -> WorkflowDraft:
    question, turn = last_turn(messages)
    results: dict[str, ToolResultBlock] = {
        b.tool_use_id: b for m in turn for b in m.content if isinstance(b, ToolResultBlock)
    }
    steps: list[WorkflowStep] = []
    skipped: list[SkippedCall] = []
    writes: list[int] = []
    for message in turn:
        for block in message.content:
            if not isinstance(block, ToolUseBlock):
                continue
            reason = NOT_REPLAYABLE.get(block.name)
            result = results.get(block.id)
            tool = agent.tools.get(block.name)
            if reason is None and tool is None:
                reason = "outil indisponible pour cet agent"
            if reason is None and result is None:
                reason = "jamais exécuté (validation en attente ou tour interrompu)"
            if reason is None and result is not None and result.is_error:
                reason = "refusé ou en erreur"
            if reason:
                skipped.append(SkippedCall(tool=block.name, reason=reason))
                continue
            steps.append(WorkflowStep(tool=block.name, input=dict(block.input)))
            if tool is not None and tool.requires_approval:
                writes.append(len(steps))
    if not steps:
        raise WorkflowError(
            "Aucun appel d'outil réutilisable dans le dernier tour : il faut au moins une "
            "action réussie (lecture, requête, publication…) pour en faire un workflow."
        )
    first_line = question.splitlines()[0] if question else ""
    title = first_line[:117] + "…" if len(first_line) > 120 else first_line
    description = f"Enregistré depuis une conversation avec {agent.display_name}."
    if question:
        excerpt = question if len(question) <= 300 else question[:299] + "…"
        description += f" Demande d'origine : « {excerpt} »"
    return WorkflowDraft(
        agent=agent.name,
        title=title or f"Workflow — {agent.display_name}",
        description=description[:500],
        steps=steps,
        skipped=skipped,
        writes=writes,
    )


# ─── Paramètres ───────────────────────────────────────────────────

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _typed(text: str) -> Any:
    """Valeur d'un paramètre qui remplace TOUTE une valeur : nombre ou booléen si c'en est un."""
    if _NUMBER.fullmatch(text):
        return float(text) if "." in text else int(text)
    if text in {"true", "false"}:
        return text == "true"
    return text


def substitute(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value.strip())
        if whole:
            return _typed(values[whole.group(1)])
        return PLACEHOLDER.sub(lambda m: values[m.group(1)], value)
    if isinstance(value, dict):
        return {k: substitute(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, values) for v in value]
    return value


def resolve_params(declared: Sequence[WorkflowParam], given: dict[str, str]) -> dict[str, str]:
    unknown = sorted(set(given) - {p.name for p in declared})
    if unknown:
        raise WorkflowError(f"Paramètre(s) inconnu(s) : {', '.join(unknown)}.")
    values: dict[str, str] = {}
    for param in declared:
        value = given.get(param.name, "").strip() or param.default
        if not value:
            raise WorkflowError(f"Renseignez « {param.label or param.name} ».")
        values[param.name] = value
    return values


# ─── Exécution ────────────────────────────────────────────────────


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CONTENT else text[: MAX_CONTENT - 1] + "…"


async def run_workflow(
    agent: BaseAgent,
    steps: Sequence[WorkflowStep],
    declared: Sequence[WorkflowParam],
    given: dict[str, str],
    approvals: dict[str, bool] | None,
    context: ToolContext | None = None,
) -> WorkflowRunResult:
    values = resolve_params(declared, given)
    concrete = [(step, substitute(step.input, values)) for step in steps]

    # 1. Porte de contrôle : tout est vérifié avant d'exécuter quoi que ce soit
    problems: list[str] = []
    for index, (step, tool_input) in enumerate(concrete, start=1):
        tool = agent.tools.get(step.tool)
        if tool is None:
            problems.append(
                f"Étape {index} : l'outil « {step.tool} » n'est pas disponible (application "
                "non configurée, ou retirée de l'agent)."
            )
            continue
        try:
            tool.input_model.model_validate(tool_input)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(racine)'} : {e['msg']}"
                for e in exc.errors()
            )
            problems.append(f"Étape {index} ({step.tool}) : paramètres invalides — {details}")
    if problems:
        return WorkflowRunResult(status="failed", message=" ".join(problems))

    # 2. Validation humaine des écritures, comme dans le chat
    pending = [
        PendingStep(
            index=index, tool=step.tool, summary=agent.tools[step.tool].summarize(tool_input)
        )
        for index, (step, tool_input) in enumerate(concrete, start=1)
        if agent.tools[step.tool].requires_approval and str(index) not in (approvals or {})
    ]
    if pending:
        return WorkflowRunResult(
            status="awaiting_approval",
            message="Ce workflow modifie des données : autorisez ou refusez chaque action.",
            pending=pending,
        )

    # 3. Exécution dans l'ordre, contexte partagé ; arrêt à la première erreur
    ctx = context or ToolContext()
    results: list[StepResult] = []
    artifacts: list[Artifact] = []
    failed = False
    for index, (step, tool_input) in enumerate(concrete, start=1):
        tool = agent.tools[step.tool]
        base = {"index": index, "tool": step.tool, "label": step.label, "input": tool_input}
        if failed:
            results.append(StepResult(**base, status="skipped"))
            continue
        if tool.requires_approval and not (approvals or {}).get(str(index), False):
            results.append(StepResult(**base, status="refused", content="Action refusée."))
            continue
        output = await tool.invoke(tool_input, ctx)
        artifacts.extend(output.artifacts)
        results.append(
            StepResult(
                **base, status="error" if output.is_error else "ok", content=_clip(output.content)
            )
        )
        failed = output.is_error
    if failed:
        where = next(r for r in results if r.status == "error")
        return WorkflowRunResult(
            status="failed",
            message=f"Arrêt à l'étape {where.index} ({where.tool}) : {where.content}",
            steps=results,
            artifacts=artifacts,
        )
    done = sum(r.status == "ok" for r in results)
    refused = sum(r.status == "refused" for r in results)
    message = f"{done} étape(s) exécutée(s)" + (f", {refused} refusée(s)" if refused else "")
    return WorkflowRunResult(
        status="completed",
        message=message + f", {len(artifacts)} livrable(s).",
        steps=results,
        artifacts=artifacts,
    )
