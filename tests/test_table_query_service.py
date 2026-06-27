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
    assert result.payload()["rows"][0]["amount_mat"] is None


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
    assert "Монтаж кабеля" in result.answer


def test_table_query_compare_is_table_query(tmp_path):
    storage_root, dataset_id = _build_smeta_parquet(tmp_path)
    chunk = Chunk(
        content="Монтаж",
        doc_name="smeta.csv",
        meta={"dataset_id": dataset_id, "parquet_path": "_parquet/smeta.parquet"},
    )

    result = maybe_answer_table_query(
        "сравни позиции монтаж кабеля и монтаж лотка",
        [chunk],
        storage_root=storage_root,
    )

    assert result is not None
    assert result.operation == "compare"
    assert result.count == 2


def _build_cable_parquet(tmp_path: Path) -> tuple[Path, str]:
    """Смета с 25 строками кабеля 3х1,5 (qty=10) + шум — больше прежнего cap=20."""
    dataset_id = "ds-cable"
    data_dir = tmp_path / "storage" / "datasets" / dataset_id
    data_dir.mkdir(parents=True)
    csv_path = data_dir / "vor.csv"
    rows = ["№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма"]
    for i in range(1, 26):
        rows.append(f'{i},"Кабель медный 3х1,5 мм2 ППГнг N{i}",м,10,0,0')
    rows.append('26,"Кабель медный 3х2,5 мм2 ППГнг",м,99,0,0')
    rows.append("27,Монтаж лотка,м,5,0,0")
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    result = asyncio.run(
        TableNormalizer(parquet_dir=str(data_dir / "_parquet"), use_llm=False).process(
            str(csv_path),
            dataset_id=dataset_id,
        )
    )
    assert result["parquet_path"]
    return tmp_path / "storage" / "datasets", dataset_id


def test_aggregate_sums_full_parquet_beyond_cap(tmp_path):
    storage_root, dataset_id = _build_cable_parquet(tmp_path)
    chunk = Chunk(
        content="Кабель",
        doc_name="vor.csv",
        meta={
            "dataset_id": dataset_id,
            "parquet_path": "_parquet/vor.parquet",
            "type": "table_row",
        },
    )

    result = maybe_answer_table_query(
        "сколько всего кабеля 3х1,5",
        [chunk],
        storage_root=storage_root,
    )

    assert result is not None
    assert result.operation == "sum"
    assert result.field == "qty"
    # 25 строк × 10 = 250 (а не первые 20 → 200); строка 3х2,5 отфильтрована.
    assert result.total == 250
    assert result.count == 25
    assert "полная выгрузка" in result.answer


def test_aggregate_subject_filter_distinguishes_size(tmp_path):
    storage_root, dataset_id = _build_cable_parquet(tmp_path)
    chunk = Chunk(
        content="Кабель",
        doc_name="vor.csv",
        meta={"dataset_id": dataset_id, "parquet_path": "_parquet/vor.parquet"},
    )

    result = maybe_answer_table_query(
        "суммарный кабель 3х2,5",
        [chunk],
        storage_root=storage_root,
    )

    assert result is not None
    assert result.total == 99
    assert result.count == 1


def test_aggregate_falls_back_when_no_subject(tmp_path):
    storage_root, dataset_id = _build_cable_parquet(tmp_path)
    chunk = Chunk(
        content="Кабель",
        doc_name="vor.csv",
        meta={"dataset_id": dataset_id, "parquet_path": "_parquet/vor.parquet"},
    )

    # Нет предмета → агрегация не срабатывает, обычная ветка (list) отвечает.
    result = maybe_answer_table_query(
        "итого по таблице",
        [chunk],
        storage_root=storage_root,
    )

    assert result is None or result.operation != "sum" or "полная выгрузка" not in result.answer


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
