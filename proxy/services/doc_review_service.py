"""Doc-review engine (СПДС-нормоконтроль, Phase 3) — RAG-led SPDS review.

Прогоняет комплект (DocumentSet) по review-map и собирает структурированные review-items
(docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md §5). АРХИТЕКТУРА:
  • computed-checks (формализуемое) → evidence-статус (computed_issue / supported_by_evidence /
    not_applicable). Переиспользуют normcontrol_service (NK-03/NK-04), не дублируют.
  • retrieval-цели → review_needed (RAG-поиск требования стандарта — отдельная под-фаза).
  • layout/manual_required → manual_required (без уверенного extraction вердикта нет).
  • human_decision у каждого item = unset: финальный статус даёт инженер, не движок.
Движок НЕ выносит юридического решения — он предлагает proposed issues с requirement/document source_ref.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from proxy.services.document_set_model import DocumentSet, VedomostMatch, build_document_set, match_vedomost
from proxy.services.normcontrol_review_map_service import ReviewMap, ReviewTarget
from proxy.services.normcontrol_service import check_cipher_consistency

# Статусы review-item (см. §5). Финальные (confirmed/rejected) ставит человек, не движок.
S_COMPUTED_ISSUE = "computed_issue"
S_SUPPORTED = "supported_by_evidence"
S_NOT_APPLICABLE = "not_applicable"
S_MANUAL = "manual_required"
S_REVIEW_NEEDED = "review_needed"


@dataclass
class ReviewItem:
    rule_id: str
    clause: str
    status: str
    severity: str
    target: str
    requirement: dict          # {source_ref, snippet} — ссылка на пункт ГОСТ
    document_evidence: list    # [{kind, source_ref, snippet}]
    computed_check: dict       # {name, status: ok|issue|not_run}
    model_note: str            # пояснение модели (заполняется позже), не вердикт
    human_decision: str = "unset"  # unset|confirmed|rejected|needs_more_evidence
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _requirement(standard: str, clause: str) -> dict:
    return {"source_ref": f"{standard}#clause={clause}" if clause else standard, "snippet": ""}


def _doc_ev(targets: list[str]) -> list:
    return [{"kind": "document", "source_ref": t, "snippet": ""} for t in targets[:20]]


def _run_computed(target: ReviewTarget, doc_set: DocumentSet, ved: VedomostMatch | None):
    """Возвращает (status, computed_check, document_evidence, note) для computed-цели.
    None → computed-движка для этого check нет (вызывающий пометит manual_required)."""
    check = target.check

    if check == "rulepack_version_gate":
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], "Выбран ГОСТ Р 21.101-2026."

    if check == "base_designation_consistency":
        names = [d.file_name for d in doc_set.documents]
        warns = [f for f in check_cipher_consistency(names) if f.severity == "warning"]
        if warns:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"}, _doc_ev([f.target for f in warns]),
                    "Шифр части файлов расходится с основным (может быть и несколько комплектов — решает инженер).")
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], ""

    if check == "designation_pattern":
        bad = [d.file_name for d in doc_set.documents if d.designation is None]
        if bad:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"}, _doc_ev(bad),
                    "Обозначение СПДС не распознано в имени файла.")
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], ""

    if check == "designation_separators":
        bad = [d.file_name for d in doc_set.documents if d.designation and d.designation.bad_separators]
        if bad:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"}, _doc_ev(bad),
                    "Недопустимые пробелы/разделители в обозначении.")
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], ""

    if check in ("vedomost_vs_files", "vedomost_missing"):
        if ved is None:
            return S_NOT_APPLICABLE, {"name": check, "status": "not_run"}, [], "Ведомость не распознана — сверка пропущена."
        if ved.missing:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"},
                    _doc_ev([m["designation"] for m in ved.missing]),
                    "Документ из ведомости отсутствует в комплекте.")
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], ""

    if check == "vedomost_extra":
        if ved is None:
            return S_NOT_APPLICABLE, {"name": check, "status": "not_run"}, [], "Ведомость не распознана."
        if ved.extra:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"}, _doc_ev(ved.extra),
                    "Файл присутствует в комплекте, но не указан в ведомости.")
        return S_SUPPORTED, {"name": check, "status": "ok"}, [], ""

    if check == "electronic_readiness":
        from proxy.services.document_set_model import SUPPORTED_EXT
        bad = [d.file_name for d in doc_set.documents if d.ext and d.ext not in SUPPORTED_EXT]
        if bad:
            return (S_COMPUTED_ISSUE, {"name": check, "status": "issue"}, _doc_ev(bad),
                    "Неподдерживаемый формат файла.")
        # формат ок, но текстовый слой требует sidecar/OCR-проверки → не финальный pass
        return S_MANUAL, {"name": check, "status": "ok"}, [], "Формат поддерживается; текстовый слой проверяется отдельно (sidecar/OCR)."

    return None  # computed-движка нет → manual_required


def run_review(doc_set: DocumentSet, review_map: ReviewMap, *, vedomost_entries: list[dict] | None = None) -> list[ReviewItem]:
    """Прогон комплекта по review-map → список review-items. Чистая функция (без живых сервисов)."""
    ved = match_vedomost(doc_set, vedomost_entries) if vedomost_entries is not None else None
    items: list[ReviewItem] = []
    for t in review_map.targets:
        req = _requirement(review_map.standard, t.clause)
        if t.kind == "computed":
            res = _run_computed(t, doc_set, ved)
            if res is not None:
                status, cc, ev, note = res
                items.append(ReviewItem(t.id, t.clause, status, t.severity, t.title, req, ev, cc, note))
                continue
            # computed заявлен, но движка нет — честно manual, не fake pass
            items.append(ReviewItem(t.id, t.clause, S_MANUAL, t.severity, t.title, req, [],
                                    {"name": t.check, "status": "not_run"}, "Автопроверка не реализована."))
        elif t.kind == "retrieval":
            items.append(ReviewItem(t.id, t.clause, S_REVIEW_NEEDED, t.severity, t.title, req, [],
                                    {"name": t.check, "status": "not_run"},
                                    "Требование/база ищется в RAG (под-фаза retrieval)."))
        else:  # layout | manual_required
            items.append(ReviewItem(t.id, t.clause, S_MANUAL, t.severity, t.title, req, [],
                                    {"name": t.check, "status": "not_run"},
                                    "Нужна ручная проверка (layout/штамп/изменения)."))
    return items


def review_summary(items: list[ReviewItem]) -> dict:
    by_status: dict[str, int] = {}
    for it in items:
        by_status[it.status] = by_status.get(it.status, 0) + 1
    return {"total": len(items), "by_status": by_status,
            "computed_issues": by_status.get(S_COMPUTED_ISSUE, 0),
            "manual_required": by_status.get(S_MANUAL, 0),
            "review_needed": by_status.get(S_REVIEW_NEEDED, 0)}


# ── оркестратор: dataset_id → review (файлы из MetaDB, ведомость из Parquet) ──
# Используется и роутером /api/doc-review, и чат-инструментом doc_review (агент-роутер).

def _dataset_file_names(dataset_id: str) -> list[str]:
    import sqlite3

    from backend.rag_config import rag_meta_db_path

    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            rows = conn.execute(
                "SELECT file_name FROM documents WHERE dataset_id=?", (dataset_id,)
            ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _vedomost_entries(dataset_id: str, storage_root: Path = Path("storage/datasets")):
    """Позиции ведомости (VEDOMOST в Parquet) → [{designation, name}]. None если ведомости нет."""
    try:
        from proxy.services.bor_service import rows_from_parquet
    except Exception:
        return None
    parquet_root = storage_root / dataset_id / "_parquet"
    if not parquet_root.exists():
        return None
    entries: list[dict] = []
    for pq in sorted(parquet_root.rglob("*.parquet")):
        try:
            for row in rows_from_parquet(pq):
                if row.get("doc_type") == "VEDOMOST":
                    ref = str(row.get("designation") or row.get("code") or "").strip()
                    if ref:
                        entries.append({"designation": ref, "name": str(row.get("name") or "").strip()})
        except Exception:
            continue
    return entries or None


def review_dataset(dataset_id: str, *, rulepack: str = "gost_r_21_101_2026"):
    """dataset_id → (review_map, items). Поднимает ValueError('no_documents') если файлов нет,
    FileNotFoundError/ValueError если rulepack битый (валидирует load_review_map)."""
    from proxy.services.normcontrol_review_map_service import load_review_map

    review_map = load_review_map(rulepack)
    files = _dataset_file_names(dataset_id)
    if not files:
        raise ValueError("no_documents")
    vedomost = _vedomost_entries(dataset_id)
    doc_set = build_document_set(files)
    return review_map, run_review(doc_set, review_map, vedomost_entries=vedomost)


def review_to_chat_text(items: list[ReviewItem], review_map: ReviewMap, *, top: int = 8) -> str:
    """Краткий человекочитаемый ответ для чата (RAG-led: предлагаемые замечания, не вердикт)."""
    s = review_summary(items)
    lines = [
        f"**Нормоконтроль комплекта — {review_map.standard} (СПДС, предварительно)**",
        "",
        f"Позиций проверки: {s['total']} · замечаний (код): {s['computed_issues']} · "
        f"ручных проверок: {s['manual_required']} · нужен обзор требования: {s['review_needed']}.",
    ]
    issues = [it for it in items if it.status in (S_COMPUTED_ISSUE, S_MANUAL)]
    if issues:
        lines.append("")
        for it in issues[:top]:
            lines.append(f"- [{it.rule_id} · {_STATUS_RU.get(it.status, it.status)}] "
                         f"{it.target}: {it.model_note}")
        if len(issues) > top:
            lines.append(f"… и ещё {len(issues) - top} (показаны первые {top}).")
    lines += ["", "_Статусы предлагаемые: код считает формализуемое, требования ищет RAG; "
              "финальное решение по каждому пункту — за инженером._"]
    return "\n".join(lines)


def review_to_json(items: list[ReviewItem], review_map: ReviewMap) -> dict:
    return {"standard": review_map.standard, "rulepack": review_map.name, "version": review_map.version,
            "summary": review_summary(items), "items": [it.to_dict() for it in items],
            "note": "RAG-led SPDS review: статусы — proposed issues/evidence, финал ставит инженер."}


_STATUS_RU = {S_COMPUTED_ISSUE: "Замечание (код)", S_SUPPORTED: "Подтверждено evidence",
              S_NOT_APPLICABLE: "Неприменимо", S_MANUAL: "Ручная проверка", S_REVIEW_NEEDED: "Нужен RAG/обзор"}


def review_to_html(items: list[ReviewItem], review_map: ReviewMap) -> str:
    rows = "".join(
        f"<tr><td>{it.rule_id}</td><td>{it.clause}</td><td>{_STATUS_RU.get(it.status, it.status)}</td>"
        f"<td>{it.severity}</td><td>{it.target}</td><td>{it.model_note}</td></tr>"
        for it in items)
    s = review_summary(items)
    return (f"<!doctype html><meta charset='utf-8'><title>Нормоконтроль {review_map.standard}</title>"
            f"<h2>Проверка документации — {review_map.standard}</h2>"
            f"<p>Всего {s['total']} · замечаний(код) {s['computed_issues']} · ручных {s['manual_required']} · RAG {s['review_needed']}</p>"
            f"<p><i>RAG-led review: статусы — предлагаемые; финал ставит инженер.</i></p>"
            f"<table border=1 cellpadding=4 cellspacing=0><tr><th>Правило</th><th>Пункт</th><th>Статус</th>"
            f"<th>Severity</th><th>Объект</th><th>Пояснение</th></tr>{rows}</table>")


def review_to_xlsx(items: list[ReviewItem], output_path: Path, review_map: ReviewMap) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Нормоконтроль"
    ws.append([f"Проверка документации — {review_map.standard}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["Правило", "Пункт", "Статус", "Severity", "Объект", "Требование", "Пояснение"])
    for cell in ws[3]:
        cell.font = Font(bold=True)
    for it in items:
        ws.append([it.rule_id, it.clause, _STATUS_RU.get(it.status, it.status), it.severity,
                   it.target, it.requirement.get("source_ref", ""), it.model_note])
    for col, width in {"A": 22, "B": 8, "C": 20, "D": 10, "E": 34, "F": 34, "G": 60}.items():
        ws.column_dimensions[col].width = width
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return len(items)
