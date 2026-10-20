"""Endpoints Data Via : relais lecture seule vers Atelier Viz pour le frontend
(Dashboard Data Via) et supervision du connecteur."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.errors import ErrorResponse
from app.core.config import get_settings
from app.schemas.data_via import (
    DatasetProfile,
    DatasetRows,
    DatasetSummary,
    DataViaStatus,
    QueryRequest,
    QueryResponse,
)
from app.tools.data_via import DataViaClient, DataViaNotConfiguredError

router = APIRouter(prefix="/api/data-via", tags=["data-via"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Jeu de données introuvable"},
    422: {"model": ErrorResponse, "description": "Requête refusée par Data Via"},
    503: {"model": ErrorResponse, "description": "Data Via non configuré ou injoignable"},
}


async def get_data_via_client() -> AsyncIterator[DataViaClient]:
    """Dépendance : un client par requête (surchargeable dans les tests)."""
    client = DataViaClient.from_settings(get_settings())
    if client is None:
        raise DataViaNotConfiguredError("DATA_VIA_BASE_URL n'est pas défini.")
    async with client:
        yield client


ClientDep = Annotated[DataViaClient, Depends(get_data_via_client)]


@router.get("/status", response_model=DataViaStatus)
async def status() -> DataViaStatus:
    """Atelier Viz est-il configuré et joignable ? (ne lève jamais)"""
    client = DataViaClient.from_settings(get_settings())
    if client is None:
        return DataViaStatus(configured=False, available=False, base_url=None)
    async with client:
        return await client.status()


@router.get("/datasets", response_model=list[DatasetSummary], responses=_ERRORS)
async def list_datasets(client: ClientDep) -> list[DatasetSummary]:
    return await client.list_datasets()


@router.get("/datasets/{dataset_id}", response_model=DatasetProfile, responses=_ERRORS)
async def get_dataset(dataset_id: str, client: ClientDep) -> DatasetProfile:
    return await client.get_dataset(dataset_id)


@router.get("/datasets/{dataset_id}/rows", response_model=DatasetRows, responses=_ERRORS)
async def get_rows(
    dataset_id: str,
    client: ClientDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> DatasetRows:
    return await client.get_rows(dataset_id, offset=offset, limit=limit)


@router.post("/query", response_model=QueryResponse, responses=_ERRORS)
async def query(body: QueryRequest, client: ClientDep) -> QueryResponse:
    return await client.query(body)
