import pytest

from proxy.routers import datasets, notebooks, service_sources


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
async def test_dataset_memory_endpoints(monkeypatch):
    monkeypatch.setattr(notebooks, "get_typed_dataset_memory", lambda dataset_id: {
        "schema": "dataset_memory_v1",
        "dataset_id": dataset_id,
        "is_evidence": False,
    })
    monkeypatch.setattr(notebooks, "build_typed_dataset_memory", lambda dataset_id, **_kw: {
        "schema": "dataset_memory_v1",
        "dataset_id": dataset_id,
        "reader_status": "bootstrap",
    })

    result = await notebooks.dataset_typed_memory("ds-1", _user=object())
    refreshed = await notebooks.refresh_dataset_typed_memory("ds-1", _admin=object())

    assert result["is_evidence"] is False
    assert refreshed["reader_status"] == "bootstrap"


@pytest.mark.asyncio
async def test_dataset_guidance_endpoint(monkeypatch):
    calls = []

    def fake_set(dataset_id, guidance, **kwargs):
        calls.append((dataset_id, guidance, kwargs))
        return {
            "dataset_id": dataset_id,
            "operator_guidance": guidance,
            "operator_guidance_role": "navigation_not_evidence",
        }

    monkeypatch.setattr(datasets, "set_dataset_operator_guidance", fake_set)

    result = await datasets.update_dataset_operator_guidance(
        "ds-1",
        datasets.DatasetGuidanceRequest(guidance="сначала смотреть ПЗ"),
        _admin=object(),
    )

    assert result["operator_guidance_role"] == "navigation_not_evidence"
    assert calls[0][0] == "ds-1"
    assert calls[0][1] == "сначала смотреть ПЗ"


@pytest.mark.asyncio
async def test_dataset_kind_endpoint(monkeypatch):
    calls = []

    def fake_set(dataset_id, kind, **kwargs):
        calls.append((dataset_id, kind, kwargs))
        return {
            "dataset_id": dataset_id,
            "dataset_kind": "project",
            "dataset_kind_label": "Проект",
        }

    monkeypatch.setattr(datasets, "set_dataset_kind", fake_set)

    result = await datasets.update_dataset_kind(
        "ds-1",
        datasets.DatasetKindRequest(kind="проект"),
        _admin=object(),
    )

    assert result["dataset_kind"] == "project"
    assert calls[0][0] == "ds-1"
    assert calls[0][1] == "проект"


@pytest.mark.asyncio
async def test_dataset_memory_reader_endpoint(monkeypatch):
    async def fake_reader(dataset_id, **_kw):
        return {
            "schema": "dataset_memory_v1",
            "dataset_id": dataset_id,
            "reader_status": "model",
            "reader_output": {"corpus_kind": "project"},
        }

    monkeypatch.setattr(notebooks, "run_dataset_reader_pass", fake_reader)
    monkeypatch.setattr(notebooks, "schedule_dataset_reader_pass", lambda dataset_id, **_kw: {
        "scheduled": True,
        "dataset_id": dataset_id,
    })

    result = await notebooks.read_dataset_memory(
        "ds-1",
        notebooks.DatasetReaderRequest(force=True),
        _admin=object(),
    )
    background = await notebooks.read_dataset_memory(
        "ds-1",
        notebooks.DatasetReaderRequest(background=True),
        _admin=object(),
    )

    assert result["reader_status"] == "model"
    assert background["scheduled"] is True


@pytest.mark.asyncio
async def test_service_source_notebooks_endpoint(monkeypatch):
    monkeypatch.setattr(service_sources, "service_source_notebooks", lambda: {
        "schema": "notebook_v1",
        "notebooks": [{"id": "gesn"}],
    })

    result = await service_sources.list_service_source_notebooks(_user=object())

    assert result["notebooks"][0]["id"] == "gesn"
