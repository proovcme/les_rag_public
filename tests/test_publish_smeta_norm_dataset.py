import importlib.util
import sqlite3


def test_norm_cards_keep_typed_identity_and_searchable_work_description(tmp_path):
    spec = importlib.util.find_spec("tools.publish_smeta_norm_dataset")
    assert spec is not None, "ordinary smeta norm RAG publisher is missing"

    from tools.publish_smeta_norm_dataset import norm_cards

    base = tmp_path / "norms.sqlite"
    with sqlite3.connect(base) as conn:
        conn.execute(
            "CREATE TABLE norms (norm_id TEXT, norm_key TEXT, display_code TEXT, "
            "base_type TEXT, norm_name TEXT, norm_unit TEXT, work_steps TEXT)"
        )
        conn.execute(
            "CREATE TABLE resources (parent_norm_id TEXT, kind TEXT, resource_code TEXT, resource_name TEXT)"
        )
        conn.execute(
            "INSERT INTO norms VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("n1", "gesnm:10-06-048-05", "ГЭСНм10-06-048-05", "gesnm", "Прокладка кабеля оптического", "100 м", '["Размотка кабеля", "Прокладка в траншее"]'),
        )

    cards = norm_cards(base)

    assert cards == [{
        "norm_key": "gesnm:10-06-048-05",
        "norm_code": "ГЭСНм10-06-048-05",
        "base_type": "gesnm",
        "measure_unit": "100 м",
        "text": "Шифр: ГЭСНм10-06-048-05\nНаименование работы: Прокладка кабеля оптического\nИзмеритель: 100 м\nСостав работ: Размотка кабеля; Прокладка в траншее",
    }]


def test_point_payload_is_an_ordinary_dataset_chunk():
    from tools import publish_smeta_norm_dataset as publisher

    payload_builder = getattr(publisher, "point_payload", None)
    assert callable(payload_builder), "ordinary unified-collection payload builder is missing"

    payload = payload_builder(
        {
            "norm_key": "gesnm:10-06-048-05",
            "norm_code": "ГЭСНм10-06-048-05",
            "base_type": "gesnm",
            "measure_unit": "100 м",
            "text": "Шифр: ГЭСНм10-06-048-05",
        },
        dataset_id="dataset-norms",
        doc_id="document-norms",
        chunk_ord=7,
    )

    assert payload["dataset_id"] == "dataset-norms"
    assert payload["doc_id"] == "document-norms"
    assert payload["file_name"] == "smeta_norm_cards.v1"
    assert payload["chunk_ord"] == 7
    assert payload["source_role"] == "normative_reference"
    assert payload["text"] == "Шифр: ГЭСНм10-06-048-05"
