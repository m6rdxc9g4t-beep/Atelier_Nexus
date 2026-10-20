"""Outils système génériques, utilisables par tous les agents."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput


class CurrentDateTimeInput(ToolInput):
    timezone: str = Field(
        default="Europe/Paris",
        description="Fuseau horaire IANA, par ex. Europe/Paris ou America/New_York.",
    )


class CurrentDateTimeTool(BaseTool[CurrentDateTimeInput]):
    name = "current_datetime"
    description = (
        "Renvoie la date et l'heure actuelles dans un fuseau horaire donné. "
        "À utiliser pour tout calcul relatif à aujourd'hui (périodes, échéances)."
    )
    input_model = CurrentDateTimeInput

    async def run(self, params: CurrentDateTimeInput, ctx: ToolContext) -> ToolOutput:
        try:
            tz = ZoneInfo(params.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ToolOutput(content=f"Fuseau inconnu : {params.timezone}", is_error=True)
        now = datetime.now(tz)
        return ToolOutput(content=f"{now.isoformat(timespec='seconds')} ({now:%A}, {tz.key})")
