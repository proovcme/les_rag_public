from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Chunk:
    content:  str
    doc_id:   str
    doc_name: str
    score:    float
    meta:     Dict[str, Any]


@dataclass
class DatasetInfo:
    id:          str
    name:        str
    status:      str
    doc_count:   int
    chunk_count: int


class RAGBackend(ABC):
    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def list_datasets(self) -> List[DatasetInfo]: ...

    @abstractmethod
    async def create_dataset(self, name: str) -> str: ...

    @abstractmethod
    async def upload_file(self, dataset_id: str, file_path: Path, relative_path: Optional[str] = None) -> str: ...

    @abstractmethod
    async def parse_dataset(self, dataset_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        dataset_ids: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Chunk]: ...
