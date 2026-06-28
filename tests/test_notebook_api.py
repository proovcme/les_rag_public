import pytest

from proxy.routers import notebooks, service_sources


@pytest.mark.asyncio
async def test_dataset_notebook_endpoint(monkeypatch):
    monkeypatch.setattr(notebooks, "build_dataset_notebook", lambda dataset_id, **_kw: {
        "schema": "notebook_v1",
        "dataset_id": dataset_id,
        "notebook_summary": {"purpose": "navigation"},
        "is_evidence": False,
    })

    result = await notebooks.dataset_notebook("ds-1", _user=object())

    assert result["schema"] == "notebook_v1"
    assert result["dataset_id"] == "ds-1"
    assert result["is_evidence"] is False


@pytest.mark.asyncio
async def test_notebook_warmup_endpoint(monkeypatch):
    monkeypatch.setattr(notebooks, "warmup_dataset_notebooks", lambda **_kw: {
        "schema": "notebook_v1",
        "kind": "notebook_warmup",
        "built": 1,
    })

    result = await notebooks.warmup_notebooks(notebooks.NotebookWarmupRequest(dataset_ids=["ds-1"]), _admin=object())

    assert result["kind"] == "notebook_warmup"
    assert result["built"] == 1


@pytest.mark.asyncio
async def test_service_source_notebooks_endpoint(monkeypatch):
    monkeypatch.setattr(service_sources, "service_source_notebooks", lambda: {
        "schema": "notebook_v1",
        "notebooks": [{"id": "gesn"}],
    })

    result = await service_sources.list_service_source_notebooks(_user=object())

    assert result["notebooks"][0]["id"] == "gesn"
