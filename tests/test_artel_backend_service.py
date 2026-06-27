"""АРТЕЛЬ бэкенд-сервис — поток: техлист→спец→approve→план→задание→отчёт. 0 LLM в ядре."""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEL_DB_PATH", str(tmp_path / "artel.db"))
    # ФОП с ADSK_Наименование, чтобы shared-параметр резолвился.
    fop = tmp_path / "fop.txt"
    fop.write_text(
        "*GROUP\tID\tNAME\nGROUP\t1\tИд\n"
        "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
        "PARAM\t4f5cb6a1-0000-0000-0000-000000000000\tADSK_Наименование\tTEXT\t\t1\t1\tНаим\t1",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARTEL_SHARED_PARAMS_FILE", str(fop))
    import tools.artel_backend_service as s
    importlib.reload(s)
    return s


KORF_TABLE = [
    ["Модель", "А, мм", "Б, мм", "В, мм"],
    ["MPU 400", "1075", "525", "975"],
    ["MPU 700", "1075", "600", "1100"],
]


def test_extract_then_compile_flow(svc):
    rec = svc.extract_spec_from_table(KORF_TABLE, "KORF MPU", "Mechanical Equipment")
    assert rec["status"] == "draft"
    assert len(rec["spec"]["types"]) == 2

    # привязать геометрию (архетип) и утвердить
    svc.update_spec(rec["id"], geometry={
        "schema_version": "artel.family_geometry.v1", "archetype": "rect_cabinet",
        "bindings": {"width": "Длина", "depth": "Глубина", "height": "Высота"},
    })
    svc.approve_spec(rec["id"])
    assert svc.get_spec(rec["id"])["status"] == "approved"

    plan = svc.compile_plan(rec["id"])
    assert plan["status"] == "ok"
    assert any(o["op"] == "create_extrusion" for o in plan["operations"])
    # shared-параметр получил GUID из ФОП
    sp = next(o for o in plan["operations"] if o["op"] == "add_shared_parameter")
    assert sp["guid"] == "4f5cb6a1-0000-0000-0000-000000000000"


def test_job_queue_roundtrip(svc):
    rec = svc.extract_spec_from_table(KORF_TABLE, "KORF MPU", "Mechanical Equipment")
    svc.approve_spec(rec["id"])
    job = svc.create_job(rec["id"])
    assert job["status"] == svc.JOB_PENDING
    assert job["plan"]["status"] == "ok"

    # плагин забирает задание
    picked = svc.next_job()
    assert picked["id"] == job["id"] and picked["status"] == svc.JOB_RUNNING
    assert svc.next_job() is None  # больше pending нет

    # плагин шлёт отчёт
    svc.submit_report(job["id"], {"status": "pass", "executed_count": 5})
    done = svc.get_job(job["id"])
    assert done["status"] == svc.JOB_DONE
    assert done["report"]["executed_count"] == 5


def test_failed_report_marks_job_failed(svc):
    rec = svc.extract_spec_from_table(KORF_TABLE, "X", "Furniture")
    svc.approve_spec(rec["id"])
    job = svc.create_job(rec["id"])
    svc.next_job()
    svc.submit_report(job["id"], {"status": "fail", "failed_count": 2})
    assert svc.get_job(job["id"])["status"] == svc.JOB_FAILED


def test_list_specs_and_jobs(svc):
    a = svc.extract_spec_from_table(KORF_TABLE, "A", "Furniture")
    svc.extract_spec_from_table(KORF_TABLE, "B", "Furniture")
    assert len(svc.list_specs()) == 2
    svc.approve_spec(a["id"])
    svc.create_job(a["id"])
    assert len(svc.list_jobs()) == 1


def test_report_writes_learning_case_with_failures(svc):
    rec = svc.extract_spec_from_table(KORF_TABLE, "KORF MPU", "Mechanical Equipment")
    svc.approve_spec(rec["id"])
    job = svc.create_job(rec["id"])
    svc.next_job()
    svc.submit_report(job["id"], {
        "status": "fail", "operation_count": 3, "executed_count": 1,
        "results": [
            {"op": "add_family_parameter", "target": "Длина", "status": "failed", "message": "already in use"},
            {"op": "create_extrusion", "target": "body", "status": "deferred", "message": "geom"},
            {"op": "assign_material", "target": "Корпус", "status": "ok", "message": "ok"},
        ],
    })
    cases = svc.list_learning(rec["id"])
    assert len(cases) == 1
    case = cases[0]["case"]
    assert case["outcome"] == "fail"
    assert "add_family_parameter/Длина: already in use" in case["known_failures"]
    assert "create_extrusion/body" in case["deferred"]


def test_accept_job_creates_catalog_entry(svc):
    rec = svc.extract_spec_from_table(KORF_TABLE, "KORF MPU", "Mechanical Equipment")
    svc.update_spec(rec["id"], geometry={
        "schema_version": "artel.family_geometry.v1", "archetype": "rect_cabinet",
        "bindings": {"width": "Длина", "depth": "Глубина", "height": "Высота"}})
    svc.approve_spec(rec["id"])
    job = svc.create_job(rec["id"])
    svc.next_job()

    # нельзя принять незавершённое
    with pytest.raises(ValueError):
        svc.accept_job(job["id"])

    svc.submit_report(job["id"], {"status": "pass", "executed_count": 8,
                                  "autorun": {"saved_rfa": "C:/tmp/mpu.rfa"}})
    entry = svc.accept_job(job["id"])
    assert entry["name"] == "KORF MPU"
    assert entry["archetype"] == "rect_cabinet"
    assert entry["rfa_path"] == "C:/tmp/mpu.rfa"

    found = svc.list_catalog("korf")
    assert len(found) == 1 and found[0]["id"] == entry["id"]
    assert svc.list_catalog("несуществует") == []
