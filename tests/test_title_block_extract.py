"""Тест детектора основной надписи (штампа) по ГОСТ Р 21.101 — Phase 5 нормоконтроля.

Детект по тексту листа (сигнатуры полей штампа), без layout-парсинга PDF. Неуверенно → не врём.
"""

from proxy.services import title_block_extract_service as tbx


def test_detects_stamp_from_field_signatures():
    text = ("Изм. Кол.уч. Лист № док. Подп. Дата   Стадия Лист Листов   "
            "Разраб. Иванов  Пров. Петров  Н.контр. Сидоров  Масштаб 1:100")
    tb = tbx.detect_in_text(text)
    assert tb.present is True
    assert tb.confidence >= 0.6
    assert len(tb.signatures) >= 4


def test_no_stamp_in_plain_text():
    tb = tbx.detect_in_text("Обычный абзац про требования к огнестойкости стен — штампа здесь нет.")
    assert tb.present is False
    assert tb.confidence == 0.0


def test_maybe_stamp_few_signatures():
    tb = tbx.detect_in_text("Стадия П  Листов 5  Масштаб 1:50")  # 3 сигнатуры → maybe, не present
    assert tb.present is False
    assert 0.0 < tb.confidence < 0.6


def test_detect_dataset_no_real_pdf_is_safe():
    out = tbx.detect_dataset(["/nope/a.pdf", "/nope/b.txt"], sample=8)
    assert out["checked"] == 1  # только .pdf берётся; .txt отброшен
    assert out["present"] == 0 and out["scan"] == 0 and out["no_stamp"] == 1  # нет файла → не падаем


def test_doc_review_title_block_computed_and_scan_aware():
    # D4-002 теперь computed: present→supported, текст-без-штампа→issue, только сканы→manual, нет PDF→manual
    from proxy.services import doc_review_service as dr
    from proxy.services.document_set_model import build_document_set
    from proxy.services.normcontrol_review_map_service import load_review_map

    rmap = load_review_map("gost_r_21_101_2026")
    ds = build_document_set(["12-АР-1.pdf", "12-КР-2.pdf"])

    def _d4(tb):
        items = dr.run_review(ds, rmap, title_block=tb)
        return next(i for i in items if i.rule_id == "G21.101-2026-D4-002")

    # штамп в текст-листах (+сканы) → supported
    assert _d4({"checked": 8, "present": 3, "scan": 5, "no_stamp": 0,
                "examples": [{"file": "12-АР-1.pdf", "present": True, "scan": False}]}).status == dr.S_SUPPORTED
    # текст-лист без штампа → computed_issue
    assert _d4({"checked": 4, "present": 0, "scan": 0, "no_stamp": 4, "examples": []}).status == dr.S_COMPUTED_ISSUE
    # только сканы → честный manual (не fake issue)
    assert _d4({"checked": 5, "present": 0, "scan": 5, "no_stamp": 0, "examples": []}).status == dr.S_MANUAL
    # нет title_block → manual
    assert _d4(None).status == dr.S_MANUAL
