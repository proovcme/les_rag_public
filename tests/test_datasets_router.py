import asyncio
from collections import deque
from dataclasses import dataclass

import pytest

from proxy.routers import datasets


@dataclass
class Dataset:
    id: str
    name: str
    status: str = "IDLE"
    doc_count: int = 0
    chunk_count: int = 0


class FakeBackend:
    def __init__(self):
        self.datasets = [Dataset("ds-1", "NTD_Index", doc_count=3, chunk_count=7)]

    async def list_datasets(self):
        return self.datasets

    async def create_dataset(self, name):
        dataset_id = f"ds-{len(self.datasets) + 1}"
        self.datasets.append(Dataset(dataset_id, name))
        return dataset_id


class FakeJobService:
    def create(self, *args, **kwargs):
        return {"id": "job-1", "started_at": "2026-05-21T00:00:00"}

    def update(self, *args, **kwargs):
        return {}


@pytest.fixture()
def dataset_state(monkeypatch):
    previous = datasets._state
    backend = FakeBackend()
    datasets.set_dataset_state(
        datasets.DatasetRouterState(
            rag_backend=backend,
            job_service=FakeJobService(),
            job_tracker={},
            log_history=deque(maxlen=10),
            parse_semaphore=asyncio.Semaphore(1),
            sync_parse_semaphore=asyncio.Semaphore(1),
        )
    )
    yield backend
    datasets._state = previous


@pytest.mark.asyncio
async def test_dataset_list_and_create_use_configured_state(dataset_state):
    assert await datasets.list_datasets(_user=object()) == [Dataset("ds-1", "NTD_Index", doc_count=3, chunk_count=7)]

    created = await datasets.create_dataset("Mail_Index", _admin=object())

    assert created == {"id": "ds-2", "name": "Mail_Index"}


@pytest.mark.asyncio
async def test_list_sources_maps_folders_to_existing_datasets(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "NTD" / "sub"
    source.mkdir(parents=True)
    (source / "doc.pdf").write_text("x")
    uuid_like = tmp_path / "RAG_Content" / "123e4567-e89b-12d3-a456-426614174000"
    uuid_like.mkdir()
    (uuid_like / "skip.pdf").write_text("x")

    sources = await datasets.list_sources(_user=object())

    assert sources == [
        {
            "folder": "NTD",
            "source_files": 1,
            "dataset_id": "ds-1",
            "dataset_status": "IDLE",
            "indexed_files": 3,
            "chunk_count": 7,
        }
    ]
