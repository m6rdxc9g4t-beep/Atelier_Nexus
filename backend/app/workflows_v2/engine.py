"""Exécution d'un workflow v2, pas à pas et persistée (docs/workflows-v2-api.md §6).

1. **Porte de contrôle** : tout le graphe est vérifié avant la première étape (étapes connues et
   disponibles, graphe sans cycle, références aux seules étapes amont, entrées valides une fois
   les paramètres connus). Un problème → rien n'est exécuté.
2. Les étapes s'exécutent dans l'ordre topologique. Pour chacune : condition `when`, résolution
   des gabarits avec les sorties réelles des étapes précédentes, validation de l'entrée.
3. Une étape `write` ou `destructive` **s'arrête** sur `awaiting_approval` avec son entrée
   résolue ; le jeton (sha256 de l'exécution, de l'étape, de `uses` et de l'entrée) ne vaut que
   pour cette action. La reprise exécute exactement l'entrée montrée.
4. Erreur : `on_error: stop` → exécution `failed`, la suite `skipped` ; `continue` → on poursuit.
   Refus → étape `refused`, exécution `stopped`, la suite `skipped`. Une étape dont une étape
   amont a été sautée (condition fausse) est sautée aussi.

Aucun modèle n'est appelé. La définition est figée au lancement : modifier le workflow pendant
une validation ne change pas ce qui sera exécuté. Rien des données des étapes n'est journalisé.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.workflows import WorkflowRepository
from app.schemas.workflows_v2 import (
    PendingApproval,
    StepRun,
    WorkflowRun,
    WorkflowStepV2,
    WorkflowV2,
    WorkflowV2Fields,
)
from app.suite.apps import app_name
from app.suite.http import NodeActionError
from app.tools.base import Artifact, ToolContext, dump_state, load_state
from app.tools.environment import ToolEnvironment
from app.tools.formatting import data_artifact, fmt, is_atelier_table
from app.workflows import MAX_CONTENT, resolve_params
from app.workflows_v2.graph import ancestors, topo_order
from app.workflows_v2.steps import NodeTarget, StepProblem, StepRegistry, ToolTarget
from app.workflows_v2.templates import (
    RefNotFoundError,
    Scope,
    StepOutcome,
    coerce_params,
    evaluate,
    has_template,
    refs_in,
    resolve,
)
from app.workflows_v2.validation import input_issues, validate_workflow

MAX_TABLE_ROWS = 1000
MAX_DATA_BYTES = 5 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CONTENT else text[: MAX_CONTENT - 1] + "…"


def approval_token(run_id: str, step_id: str, uses: str, tool_input: dict[str, Any]) -> str:
    """Jeton d'une validation : sha256(exécution, étape, uses, entrée résolue)[:32]."""
    payload = json.dumps(
        [run_id, step_id, uses, tool_input], sort_keys=True, ensure_ascii=False, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def idempotency_key(run_id: str, step_id: str) -> str:
    return f"nexus:{run_id}:{step_id}"


def bound_data(data: Any) -> Any:
    """Sortie conservée : table tronquée à 1000 lignes (`truncated: true`), JSON ≤ 5 Mo."""
    if is_atelier_table(data) and len(data["rows"]) > MAX_TABLE_ROWS:
        total = data.get("total")
        data = {
            **data,
            "rows": data["rows"][:MAX_TABLE_ROWS],
            "truncated": True,
            "total": total if isinstance(total, int) else len(data["rows"]),
        }
    try:
        size = len(json.dumps(data, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return None
    if size > MAX_DATA_BYTES:
        return {"truncated": True, "detail": "Sortie trop volumineuse pour être conservée."}
    return data


def table_preview(app: str, table: dict[str, Any]) -> Artifact:
    """Artefact `data_preview` d'une table `atelier-table/1` (même format que les outils)."""
    columns = [c for c in table["columns"] if isinstance(c, dict) and "key" in c]
    headers = [str(c.get("label") or c["key"]) for c in columns]
    rows = [[row.get(c["key"]) for c in columns] for row in table["rows"] if isinstance(row, dict)]
    numeric = {str(c.get("label") or c["key"]) for c in columns if c.get("type") == "number"}
    return data_artifact(
        f"{app_name(app)} · {table.get('label') or table.get('name') or 'table'}",
        headers,
        rows,
        numeric=numeric,
        metadata={"source": app, "format": "atelier-table/1", "truncated": table["truncated"]},
    )


def _shown(value: Any) -> str:
    if is_atelier_table(value):
        return (
            f"table « {value.get('label') or value.get('name')} » ({len(value['rows'])} ligne(s))"
        )
    if isinstance(value, list):
        return f"{len(value)} élément(s)"
    return fmt(value)


def node_summary(target: NodeTarget, tool_input: dict[str, Any]) -> str:
    shown = ", ".join(f"{k} = {_shown(v)}" for k, v in list(tool_input.items())[:6])
    more = f" (+{len(tool_input) - 6})" if len(tool_input) > 6 else ""
    label = target.action.label or target.action.id
    return f"{app_name(target.app)} · {label}" + (f" : {shown}{more}" if shown else "")


def _definition(workflow: WorkflowV2) -> dict[str, Any]:
    return {
        "agent": workflow.agent,
        "steps": [s.model_dump(mode="json") for s in workflow.steps],
        "params": [p.model_dump(mode="json") for p in workflow.params],
    }


class Engine:
    """Fait avancer UNE exécution jusqu'à la fin ou jusqu'à la prochaine validation."""

    def __init__(
        self,
        run: WorkflowRun,
        state: dict[str, Any],
        registry: StepRegistry,
        env: ToolEnvironment,
        repo: WorkflowRepository,
    ) -> None:
        self.run = run
        self.state = state
        self.registry = registry
        self.env = env
        self.repo = repo
        definition = state["definition"]
        self.steps = [WorkflowStepV2.model_validate(s) for s in definition["steps"]]
        self.by_id = {s.id: s for s in self.steps}
        self.ctx = ToolContext(
            extras={"workflow_id": run.workflow_id, "run_id": run.id},
            state=load_state(state.get("ctx", {})),
        )

    # ─── Persistance ──────────────────────────────────────────────

    async def save(self) -> WorkflowRun:
        self.state["ctx"] = dump_state(self.ctx.state)
        saved = await self.repo.save_run(self.run, self.state)
        # L'objet en mémoire reste la référence (les étapes en cours le modifient)
        self.run.updated_at = saved.updated_at
        return self.run

    def step_run(self, step_id: str) -> StepRun:
        return next(s for s in self.run.steps if s.id == step_id)

    def outcomes(self) -> dict[str, StepOutcome]:
        return {
            s.id: StepOutcome(status=s.status, content=s.content, data=s.data)
            for s in self.run.steps
            if s.status in ("ok", "error", "refused", "skipped")
        }

    def scope(self, step: WorkflowStepV2) -> Scope:
        return Scope(self.run.params, self.outcomes(), self.run.id, ancestors(self.steps, step.id))

    # ─── Boucle ───────────────────────────────────────────────────

    async def advance(self) -> WorkflowRun:
        self.run.status = "running"
        self.run.pending = []
        for step_run in self.run.steps:
            if step_run.status not in ("pending", "awaiting_approval"):
                continue
            step = self.by_id[step_run.id]
            stop = await self.execute(step, step_run)
            if step_run.status == "awaiting_approval":
                return await self.save()
            await self.save()
            if stop:
                for rest in self.run.steps:
                    if rest.status == "pending":
                        rest.status = "skipped"
                break
        return await self.finish()

    async def finish(self) -> WorkflowRun:
        steps = self.run.steps
        refused = next((s for s in steps if s.status == "refused"), None)
        fatal = self.state.get("fatal")
        if refused is not None:
            self.run.status = "stopped"
            self.run.message = (
                f"Arrêté à l'étape « {refused.id} » : action refusée, les étapes suivantes "
                "n'ont pas été exécutées."
            )
        elif fatal:
            failed = self.step_run(fatal)
            self.run.status = "failed"
            self.run.message = f"Arrêt à l'étape « {failed.id} » ({failed.uses}) : {failed.content}"
        else:
            done = sum(s.status == "ok" for s in steps)
            errors = sum(s.status == "error" for s in steps)
            self.run.status = "completed"
            self.run.message = (
                f"{done} étape(s) exécutée(s), {len(self.run.artifacts)} livrable(s)."
            )
            if errors:
                self.run.message += f" {errors} étape(s) en erreur, poursuivi (on_error: continue)."
        self.state.pop("pending", None)
        run = await self.save()
        if run.status in ("completed", "failed", "stopped"):
            await self.repo.record_run(run.workflow_id, run.status)
        return run

    # ─── Une étape ────────────────────────────────────────────────

    def fail(self, step: WorkflowStepV2, step_run: StepRun, code: str, message: str) -> bool:
        step_run.status = "error"
        step_run.error_code = code
        step_run.content = _clip(message)
        step_run.ended_at = _now()
        if step.on_error == "stop":
            self.state["fatal"] = step.id
            return True
        return False

    def prepare(
        self, step: WorkflowStepV2, step_run: StepRun, target: ToolTarget | NodeTarget | StepProblem
    ) -> dict[str, Any] | bool:
        """Entrée résolue de l'étape, ou décision immédiate (vrai = arrêter, faux = continuer)
        quand elle est sautée ou en erreur avant toute exécution."""
        # Branche non prise en amont : l'étape suit, sauf si sa condition teste justement le
        # statut de cette étape (`{{steps.x.status}}`)
        skipped = {
            n for n in step.needs if n in self.by_id and self.step_run(n).status == "skipped"
        }
        if skipped:
            handled = {
                r.name
                for _, r in refs_in(step.when.model_dump() if step.when else None)
                if r.kind == "step" and r.part == "status"
            }
            if skipped - handled:
                step_run.status = "skipped"
                step_run.content = "Étape amont non exécutée."
                step_run.ended_at = _now()
                return False
        scope = self.scope(step)
        if step.when is not None:
            try:
                left = resolve(step.when.left, scope)
                right = resolve(step.when.right, scope)
            except RefNotFoundError as exc:
                return self.fail(step, step_run, "REF_NOT_FOUND", f"Condition : {exc}")
            if not evaluate(step.when.op, left, right):
                step_run.status = "skipped"
                step_run.content = "Condition fausse : étape non exécutée."
                step_run.ended_at = _now()
                return False
        try:
            resolved = resolve(step.input, scope)
        except RefNotFoundError as exc:
            return self.fail(step, step_run, "REF_NOT_FOUND", str(exc))
        if isinstance(target, StepProblem):
            return self.fail(step, step_run, target.code, target.message)
        if isinstance(target, NodeTarget):
            resolved = coerce_params(resolved, step.input, target.action.input_schema)
        problems = input_issues(target, resolved)
        if problems:
            step_run.input = resolved
            details = "; ".join(m for _, m in problems[:5])
            return self.fail(step, step_run, "INPUT_INVALID", f"Entrée invalide — {details}")
        return dict(resolved)

    async def execute(self, step: WorkflowStepV2, step_run: StepRun) -> bool:
        """Exécute une étape ; renvoie vrai si l'exécution doit s'arrêter là."""
        step_run.started_at = step_run.started_at or _now()
        target = self.registry.lookup(step.uses)
        pending = self.state.get("pending")
        if isinstance(pending, dict) and pending.get("step_id") == step.id:
            # Reprise après décision : exactement l'entrée montrée à l'utilisateur
            tool_input: dict[str, Any] = pending["input"]
        else:
            prepared = self.prepare(step, step_run, target)
            if isinstance(prepared, bool):
                return prepared
            tool_input = prepared
        if isinstance(target, StepProblem):
            return self.fail(step, step_run, target.code, target.message)
        step_run.input = tool_input

        # Validation humaine des écritures, liée à l'entrée résolue
        if target.kind in ("write", "destructive"):
            token = approval_token(self.run.id, step.id, step.uses, tool_input)
            decision = self.state.get("approvals", {}).get(token)
            if decision is None:
                summary = (
                    target.tool.summarize(tool_input)
                    if isinstance(target, ToolTarget)
                    else node_summary(target, tool_input)
                )
                step_run.status = "awaiting_approval"
                self.run.status = "awaiting_approval"
                self.run.pending = [
                    PendingApproval(
                        step_id=step.id,
                        uses=step.uses,
                        kind="destructive" if target.kind == "destructive" else "write",
                        summary=summary,
                        token=token,
                        input=tool_input,
                    )
                ]
                self.run.message = f"Validation demandée : {summary}"
                self.state["pending"] = {"step_id": step.id, "token": token, "input": tool_input}
                return False
            self.state.pop("pending", None)
            if not decision:
                step_run.status = "refused"
                step_run.content = "Action refusée."
                step_run.ended_at = _now()
                return True

        if isinstance(target, ToolTarget):
            output = await target.tool.invoke(tool_input, self.ctx)
            self.run.artifacts.extend(output.artifacts)
            step_run.content = _clip(output.content)
            step_run.ended_at = _now()
            if output.is_error:
                stop = self.fail(step, step_run, "TOOL_ERROR", output.content)
                return stop
            step_run.status = "ok"
            step_run.data = bound_data(output.data)
            return False

        key = (
            idempotency_key(self.run.id, step.id)
            if target.action.idempotency in ("header", "field")
            else None
        )
        try:
            result = await self.env.suite().run_action(
                target.app, target.action.id, tool_input, idempotency_key=key
            )
        except NodeActionError as exc:
            return self.fail(step, step_run, exc.code, str(exc))
        except Exception as exc:  # application ou serveur MCP en panne : message, pas de données
            return self.fail(step, step_run, "NODE_ERROR", f"{app_name(target.app)} : {exc}")
        step_run.status = "ok"
        step_run.content = _clip(result.content)
        step_run.data = bound_data(result.data)
        step_run.ended_at = _now()
        if is_atelier_table(step_run.data):
            self.run.artifacts.append(table_preview(target.app, step_run.data))
        return False


# ─── Lancement et reprise ─────────────────────────────────────────


def gate_problems(
    workflow: WorkflowV2, registry: StepRegistry, params: dict[str, str]
) -> list[str]:
    """Porte de contrôle : validation du graphe, puis des entrées dont seuls les paramètres
    sont connus (les champs qui citent une étape ne sont vérifiés qu'à l'exécution)."""
    body = WorkflowV2Fields(
        version=2,
        agent=workflow.agent,
        title=workflow.title,
        description=workflow.description,
        steps=workflow.steps,
        params=workflow.params,
    )
    result = validate_workflow(body, registry)
    problems = [
        f"Étape « {e.step_id} » : {e.message}" if e.step_id else e.message for e in result.errors
    ]
    if problems:
        return problems
    scope = Scope(params, {}, "", set())
    for step in workflow.steps:
        target = registry.lookup(step.uses)
        if isinstance(target, StepProblem):
            continue
        with_steps = {f for f, r in refs_in(step.input) if r.kind == "step"}
        partial: dict[str, Any] = {}
        for key, value in step.input.items():
            if key in with_steps or (has_template(value) and _cites_run(value)):
                partial[key] = value  # gardé en gabarit : vérifié à l'exécution
                continue
            try:
                partial[key] = resolve(value, scope)
            except RefNotFoundError as exc:
                problems.append(f"Étape « {step.id} » : {exc}")
        if isinstance(target, NodeTarget):
            partial = coerce_params(partial, step.input, target.action.input_schema)
        for field, message in input_issues(target, partial):
            where = f" ({field})" if field and field not in message else ""
            problems.append(f"Étape « {step.id} »{where} : paramètres invalides — {message}")
    return problems


def _cites_run(value: Any) -> bool:
    return any(r.kind == "run" for _, r in refs_in(value))


async def start_run(
    workflow: WorkflowV2,
    given: dict[str, str],
    registry: StepRegistry,
    env: ToolEnvironment,
    repo: WorkflowRepository,
) -> WorkflowRun:
    """Lance une exécution (WorkflowError si un paramètre manque). Une exécution refusée par la
    porte de contrôle est enregistrée `failed`, sans qu'aucune étape n'ait été exécutée."""
    values = resolve_params(workflow.params, given)
    order, _ = topo_order(workflow.steps)
    by_id = {s.id: s for s in workflow.steps}
    now = _now()
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        workflow_id=workflow.id,
        status="running",
        message="",
        params=values,
        steps=[
            StepRun(id=i, uses=by_id[i].uses, label=by_id[i].label) for i in order if i in by_id
        ],
        artifacts=[],
        pending=[],
        created_at=now,
        updated_at=now,
    )
    state: dict[str, Any] = {"definition": _definition(workflow), "approvals": {}}
    problems = gate_problems(workflow, registry, values)
    if problems:
        run.status = "failed"
        run.message = "Rien n'a été exécuté. " + " ".join(problems)
        for step_run in run.steps:
            step_run.status = "skipped"
        saved = await repo.save_run(run, state)
        await repo.record_run(workflow.id, "failed")
        return saved
    run = await repo.save_run(run, state)
    return await Engine(run, state, registry, env, repo).advance()


async def resume_run(
    run: WorkflowRun,
    state: dict[str, Any],
    approvals: dict[str, bool],
    registry: StepRegistry,
    env: ToolEnvironment,
    repo: WorkflowRepository,
) -> WorkflowRun:
    """Applique la décision sur l'étape en attente et reprend. Un jeton qui ne correspond pas
    à l'action montrée est ignoré : l'exécution reste en attente."""
    pending = state.get("pending")
    if run.status != "awaiting_approval" or not isinstance(pending, dict):
        return run
    token = pending.get("token")
    if token not in approvals:
        run.message = "Aucune décision pour l'action en attente (jeton absent ou périmé) : " + (
            run.pending[0].summary if run.pending else ""
        )
        return run
    if not await repo.claim_run(run.id):  # reprise déjà en cours ailleurs
        found = await repo.get_run(run.id)
        return found[0] if found else run
    state.setdefault("approvals", {})[token] = bool(approvals[token])
    return await Engine(run, state, registry, env, repo).advance()
