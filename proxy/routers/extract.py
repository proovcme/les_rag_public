"""Structured extraction endpoint — schema-constrained JSON from a document.

POST /api/extract/structured with a JSON schema + document text; returns a
schema-valid object (cloud providers enforce it natively, local MLX via
validate-and-repair). See proxy/services/extract_service.

Intended for the hard intake subset (messy scans / unstructured text). Clean
tabular data should go through deterministic parsing (table_query), not here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from proxy.services import extract_service

router = APIRouter(prefix="/api/extract", tags=["extract"])


class StructuredExtractRequest(BaseModel):
    # "schema" shadows a BaseModel attribute → expose it via alias, store as doc_schema.
    model_config = ConfigDict(populate_by_name=True)

    doc_schema: dict = Field(alias="schema")
    context: str
    instruction: str = ""
    max_attempts: int = Field(default=3, ge=1, le=6)


@router.post("/structured")
async def structured(req: StructuredExtractRequest) -> dict:
    result = await extract_service.run_structured_extraction(
        req.doc_schema,
        req.instruction,
        req.context,
        max_attempts=req.max_attempts,
    )
    return {
        "ok": result.ok,
        "data": result.data,
        "attempts": result.attempts,
        "errors": result.errors,
    }
