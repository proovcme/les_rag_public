"""W17.3 — доменная онтология: классификационный хребет + состояния CDE (0 LLM)."""
import importlib
import time

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    monkeypatch.setenv("CAD_BIM_GRAPH_DB_PATH", str(tmp_path / "data" / "cad_bim_graph.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    import proxy.services.cad_bim_graph as cbg
    importlib.reload(cbg)
    import proxy.services.edge_service as es
    importlib.reload(es)
    import proxy.services.field_intake_service as fis
    importlib.reload(fis)
    import proxy.services.ontology_service as ont
    importlib.reload(ont)
    return ont


def _seed_elements(rows):
    """Вставить элементы (и свойства) в cad_bim-граф для теста хребта."""
    import sqlite3
    from proxy.services.cad_bim_graph import CAD_BIM_DB_PATH, init_graph_db
    init_graph_db(CAD_BIM_DB_PATH)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(CAD_BIM_DB_PATH) as conn:
        for i, r in enumerate(rows):
            conn.execute(
                "INSERT INTO cad_bim_elements"
                "(id, import_id, source_id, speckle_type, object_type, name, layer, category, family, level, material, attributes_json, source_path, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"e{i}", r.get("import_id", "imp1"), r["source_id"], "", r.get("object_type", ""),
                 r.get("name", ""), "", r.get("category", ""), r.get("family", ""), r.get("level", ""),
                 "", "{}", "", now),
            )
            for pname, pval in r.get("props", {}).items():
                conn.execute(
                    "INSERT INTO cad_bim_properties"
                    "(id, import_id, element_id, source_id, name, value, value_type, unit, property_set, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"p{i}_{pname}", r.get("import_id", "imp1"), f"e{i}", r["source_id"], pname, pval, "text", "", "", now),
                )


# ── derive_system (чистая функция, без БД) ───────────────────────────

def test_derive_system_from_property(svc):
    assert svc.derive_system("Воздуховоды", "duct", "", system_prop="П1 Приточная") == "П1 Приточная"


def test_derive_system_from_category_dict(svc):
    assert svc.derive_system("Воздуховоды", "duct", "Round Duct") == "Вентиляция"
    assert svc.derive_system("Трубопроводы ХВС", "pipe", "") == "Трубопроводы"
    assert svc.derive_system("Несущие стены", "wall", "") == "Стены"


def test_derive_system_fallback(svc):
    assert svc.derive_system("Мебель", "furniture", "") == "Прочее"


# ── классификационный хребет ─────────────────────────────────────────

def test_classification_backbone_and_traversal(svc):
    _seed_elements([
        {"source_id": "d1", "category": "Воздуховоды", "object_type": "duct", "level": "Этаж 03", "name": "Воздуховод 1"},
        {"source_id": "d2", "category": "Воздуховоды", "object_type": "duct", "level": "Этаж 03", "name": "Воздуховод 2"},
        {"source_id": "p1", "category": "Трубопроводы", "object_type": "pipe", "level": "Этаж 03", "name": "Труба 1"},
        {"source_id": "w1", "category": "Стены", "object_type": "wall", "level": "Этаж 01", "name": "Стена 1"},
    ])
    backbone = svc.classification_backbone()
    assert backbone["totals"]["elements"] == 4
    assert backbone["totals"]["floors"] == 2
    floors = {f["floor"]: f for f in backbone["floors"]}
    assert floors["Этаж 03"]["elements"] == 3
    systems3 = {s["system"]: s["elements"] for s in floors["Этаж 03"]["systems"]}
    assert systems3["Вентиляция"] == 2
    assert systems3["Трубопроводы"] == 1

    # обход: «элементы системы вентиляции на этаже 3» (нечувствительно к регистру/форме)
    hits = svc.elements_in(floor="этаж 03", system="вентиляц")
    assert {h["source_id"] for h in hits} == {"d1", "d2"}


def test_elements_in_empty_when_no_match(svc):
    _seed_elements([{"source_id": "w1", "category": "Стены", "object_type": "wall", "level": "Этаж 01"}])
    assert svc.elements_in(system="вентиляц") == []


# ── состояния CDE (ISO 19650) ────────────────────────────────────────

def test_can_transition_state_machine(svc):
    assert svc.can_transition("WIP", "Shared")
    assert svc.can_transition("Shared", "Published")
    assert svc.can_transition("WIP", "WIP")  # идемпотентно
    assert not svc.can_transition("WIP", "Published")  # нельзя миновать Shared
    assert not svc.can_transition("Archived", "WIP")  # терминальное


def test_register_and_state_transition(svc):
    c = svc.register_container("РД/ОВ/лист-3", kind="drawing", title="Вентиляция этаж 3", project_id=2)
    assert c["cde_state"] == "WIP"
    c = svc.set_container_state("РД/ОВ/лист-3", "Shared")
    assert c["cde_state"] == "Shared"
    c = svc.set_container_state("РД/ОВ/лист-3", "Published")
    assert c["cde_state"] == "Published"


def test_invalid_transition_raises(svc):
    svc.register_container("doc-1", kind="document")
    with pytest.raises(ValueError):
        svc.set_container_state("doc-1", "Published")  # WIP→Published запрещён


def test_register_does_not_reset_state(svc):
    svc.register_container("doc-2")
    svc.set_container_state("doc-2", "Shared")
    again = svc.register_container("doc-2", title="новый заголовок")
    assert again["cde_state"] == "Shared"  # повторная регистрация не откатывает в WIP
    assert again["title"] == "новый заголовок"


def test_supersede_archives_old_and_writes_edge(svc):
    svc.register_container("лист-3-рев0", kind="drawing")
    svc.set_container_state("лист-3-рев0", "Shared")
    svc.set_container_state("лист-3-рев0", "Published")
    new = svc.supersede_container("лист-3-рев1", "лист-3-рев0", kind="drawing", revision="рев1")
    assert new["supersedes"] == "лист-3-рев0"
    assert svc.get_container("лист-3-рев0")["cde_state"] == "Archived"
    # типизированное ребро supersedes записано в граф (W17.2)
    from proxy.services.edge_service import edges_for
    out = edges_for("container", "лист-3-рев1")["out"]
    assert any(e["edge_type"] == "supersedes" and e["dst_id"] == "лист-3-рев0" for e in out)


def test_cde_summary_counts(svc):
    svc.register_container("a", project_id=2)
    svc.register_container("b", project_id=2)
    svc.set_container_state("b", "Shared")
    summary = svc.cde_summary(project_id=2)
    assert summary["WIP"] == 1
    assert summary["Shared"] == 1
    assert summary["Published"] == 0


# ── Захватка-хаб (LBS) ───────────────────────────────────────────────

def test_lbs_hubs_aggregates_volumes(svc):
    from proxy.services.field_intake_service import create_entry
    create_entry("Бетон B25", 10.0, "м3", zahvatka="Захватка-1", status="confirmed")
    create_entry("Бетон B25", 5.0, "м3", zahvatka="Захватка-1", status="confirmed")
    create_entry("Кирпич", 200.0, "шт", zahvatka="Захватка-2", status="confirmed")
    create_entry("Не учитывать", 99.0, "м3", zahvatka="Захватка-2", status="pending")
    hubs = {h["zahvatka"]: h for h in svc.lbs_hubs()}
    assert hubs["Захватка-1"]["total"] == 15.0
    assert hubs["Захватка-1"]["entries"] == 2
    assert hubs["Захватка-2"]["entries"] == 1  # pending исключён
