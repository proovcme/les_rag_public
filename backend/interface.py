from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class EmbeddingContractError(RuntimeError):
    """The embedding server returned vectors from a different model than requested."""


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
    # Total registered documents. Indexed-only count is exposed separately.
    doc_count:   int
    chunk_count: int
    sensitivity: str = "P0"  # W3.3 (ADR-9): P0 local-only / P1 cloud-ok / P2 cloud-с-согласия
    group_name:  str = ""    # пользовательская группа для организации списка в САМОВАРе
    files:        int = 0
    indexed_files: int = 0
    pending_files: int = 0
    error_files: int = 0
    missing_files: int = 0
    dataset_scope: str = "user"  # user | system; ownership, not content kind
    module_id: str = ""         # owner for system datasets (smeta, normcontrol, ...)


class RAGBackend(ABC):
    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def list_datasets(self) -> List[DatasetInfo]: ...

    @abstractmethod
    async def create_dataset(self, name: str) -> str: ...

    @abstractmethod
    async def upload_file(self, dataset_id: str, file_path: Path, relative_path: Optional[str] = None) -> str: ...

    async def mark_document_error(self, dataset_id: str, document_id: str, error: str) -> None:
        """Persist a background intake failure instead of leaving the document PENDING."""
        raise NotImplementedError

    @abstractmethod
    async def register_external_file(self, dataset_id: str, source_path: Path, file_name: str) -> str:
        """Регистрирует внешний файл как источник БЕЗ копирования в storage.

        В storage остаются только производные (Parquet/_parquet); сам документ
        читается из source_path при парсинге. file_name — ключ дока (rel-путь).
        """
        ...

    @abstractmethod
    async def parse_dataset(self, dataset_id: str, limit: Optional[int] = None) -> Dict[str, Any]: ...

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        dataset_ids: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Chunk]: ...
