import asyncio
from dataclasses import dataclass
from pathlib import Path

from backend.parquet_writer import TableNormalizer
from proxy.services.table_query_service import maybe_answer_table_query


@dataclass
class Chunk:
    content: str
    doc_name: str
    meta: dict


def _build_smeta_parquet(tmp_path: Path) -> tuple[Path, str]:
    dataset_id = "ds-table"
    data_dir = tmp_path / "storage" / "datasets" / dataset_id
    data_dir.mkdir(parents=True)
    csv_path = data_dir / "smeta.csv"
    csv_path.write_text(
        "№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма\n"
        "1,Монтаж кабеля,м,12,100,1200\n"
        "2,Монтаж лотка,м,5,200,1000\n",
        encoding="utf-8",
    )
    result = asyncio.run(
        TableNormalizer(parquet_dir=str(data_dir / "_parquet"), use_llm=False).process(
            str(csv_path),
            dataset_id=dataset_id,
        )
    )
    assert result["parquet_path"]
    return tmp_path / "storage" / "datasets", dataset_id


def test_table_query_sums_filtered_parquet_rows(tmp_path):
    storage_root, dataset_id = _build_smeta_parquet(tmp_path)
    chunk = Chunk(
        content="Монтаж кабеля",
        doc_name="smeta.csv",
        meta={
            "dataset_id": dataset_id,
            "parquet_path": "_parquet/smeta.parquet",
            "type": "table_row",
        },
    )

    result = maybe_answer_table_query(
        "посчитай сумму монтаж кабеля",
        [chunk],
        storage_root=storage_root,
    )

    assert result is not None
    assert result.operation == "sum"
    assert result.field == "amount"
    assert result.total == 1200
    assert result.count == 1
    assert result.sources == ["smeta.csv"]
    assert "1 200" in result.answer


def test_table_query_lists_matching_rows(tmp_path):
    storage_root, dataset_id = _build_smeta_parquet(tmp_path)
    chunk = Chunk(
        content="Монтаж",
        doc_name="smeta.csv",
        meta={"dataset_id": dataset_id, "parquet_path": "_parquet/smeta.parquet"},
    )

    result = maybe_answer_table_query(
        "найди позиции монтаж",
        [chunk],
        storage_root=storage_root,
    )

    assert result is not None
    assert result.operation == "list"
    assert result.count == 2


def test_table_query_rejects_unsafe_parquet_path(tmp_path):
    chunk = Chunk(
        content="Монтаж",
        doc_name="smeta.csv",
        meta={"dataset_id": "ds-table", "parquet_path": "../secret.parquet"},
    )

    result = maybe_answer_table_query(
        "посчитай сумму монтаж",
        [chunk],
        storage_root=tmp_path / "storage" / "datasets",
    )

    assert result is None
