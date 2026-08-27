"""
С.О.В.У.Ш.К.А. v5.0 — вкладка Д.И.А.Г.Н.О.З.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from nicegui import ui

from sovushka.state import state, api_get, api_post, api_put, add_log, active_llm_provider
from sovushka.config import MLX_URL
from sovushka.components.charts import _html, esc
from sovushka.uikit.components import (
    acronym_identity,
    action_button,
    panel,
    section_heading,
    select_field,
    status_badge,
    text_field,
    render_feedback_state,
)


_RAG_PIPELINE_STAGE_LABELS = {
    "index": "Индекс",
    "native_rrf": "Native RRF",
    "hierarchy": "Иерархия",
    "raptor": "RAPTOR",
    "colbert": "ColBERT",
    "reranker": "Cross-encoder",
    "parent_context": "Parent / context",
    "exact_evidence": "Exact evidence",
}


def _pipeline_badge(status: str) -> tuple[str, str]:
    return {
        "ready": ("Готов", "ok"),
        "indexing": ("Индексируется", "warn"),
        "configured": ("Настроен", "warn"),
        "disabled": ("Выключен", "muted"),
        "degraded": ("Деградация", "error"),
        "blocked": ("Блокирован", "blocked"),
        "unknown": ("Нет данных", "muted"),
    }.get(str(status or "unknown").lower(), ("Нет данных", "muted"))


def _runtime_factor_value(value) -> str:
    if value is None or value == "":
        return "не задано"
    if isinstance(value, bool):
        return "включено" if value else "выключено"
    return str(value)


def _runtime_factor_source(value: str) -> str:
    labels = {
        "workflow_invariants": "правила workflow",
        "observed_backend_capacity": "фактическая ёмкость backend",
        "factory_preset": "заводской пресет",
        "operator_clone": "копия оператора",
        "workflow_profile_restrictions": "ограничения профиля",
        "unavailable": "нет наблюдения",
    }
    parts = [part.strip() for part in str(value or "unavailable").split(">")]
    return " → ".join(labels.get(part, part) for part in parts if part)


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _platform_labels() -> dict[str, str]:
    if _is_windows():
        return {
            "resources": "Ресурсы Windows",
            "model": "Ollama",
            "model_detail": "локальные модели · порт 11434",
            "runtime_detail": "Docker Desktop и локальные процессы",
        }
    return {
        "resources": "Ресурсы Mac",
        "model": "MLX Host",
        "model_detail": "локальный inference · порт 8080",
        "runtime_detail": "сервисы работают через LaunchAgents",
    }


def _build_diag_map_html(results: list) -> str:
    """Строит читаемый реестр контуров с живыми статусами узлов."""
    result_map = {r["name"]: r for r in results}
    platform = _platform_labels()

    def st(*names: str) -> str:
        for name in names:
            if name in result_map:
                return result_map[name].get("status", "idle")
        return "idle"

    def safe_status(value: str) -> str:
        return value if value in {"ok", "warn", "err", "idle"} else "idle"

    def node(title: str, subtitle: str, status: str) -> str:
        status = safe_status(status)
        label = {
            "ok": "Готов",
            "warn": "Внимание",
            "err": "Ошибка",
            "idle": "Не проверено",
        }[status]
        return (
            f'<div class="sov-config-service sov-config-service--{status}">'
            f'  <span class="sov-config-service__dot" aria-hidden="true"></span>'
            f'  <div class="sov-config-service__copy">'
            f'    <div class="sov-config-service__name">{esc(title)}</div>'
            f'    <div class="sov-config-service__detail">{esc(subtitle)}</div>'
            f'  </div>'
            f'  <span class="sov-config-service__status">{label}</span>'
            f'</div>'
        )

    def group(title: str, items: list[str]) -> str:
        return (
            '<section class="sov-config-contour">'
            f'  <h3 class="sov-config-contour__title">{esc(title)}</h3>'
            f'  <div class="sov-config-contour__body">{"".join(items)}</div>'
            '</section>'
        )

    groups = [
        group("Доступ и интерфейс", [
            node("Сеть", "интернет и внешние доступы", st("Интернет", "Сеть (интернет)")),
            node("С.О.В.У.Ш.К.А.", "веб-интерфейс · порт 8051", "ok"),
            node("les-proxy", "API и маршрутизация · порт 8050", st("les-proxy :8050")),
        ]),
        group("Поиск и данные", [
            node("Qdrant", "векторный индекс · порт 6333", st("Qdrant :6333")),
            node("Qwen index", "согласованность chunks и points", st("Qdrant индекс", "Qdrant :6333")),
            node("SQLite", "метаданные документов", st("SQLite метабаза")),
        ]),
        group("Модели", [
            node(
                platform["model"],
                platform["model_detail"],
                st("Локальная модель", "MLX Backend", "MLX Host :8080"),
            ),
            node("Latency", "время ответа модели и чата", st("Model latency", "MLX latency", "Chat latency (тест)")),
            node("Т.О.С.К.А.", "контроль качества ответов", st("Т.О.С.К.А. статистика")),
        ]),
        group(platform["resources"], [
            node("RAM", "оперативная память", st("RAM")),
            node("CPU", "текущая нагрузка", st("CPU")),
            node("Диск", "свободное место", st("Диск")),
            node("Runtime", platform["runtime_detail"], st("Docker runtime", "Docker")),
        ]),
    ]

    return (
        '<div class="sov-config-contours" role="list" '
        'aria-label="Состояние системных контуров">'
        f'{"".join(groups)}'
        '</div>'
    )


def _build_overall_status_html(status: str = "idle") -> str:
    """Возвращает главный статус конфигурации без dashboard-KPI."""
    safe_status = status if status in {"ok", "warn", "err"} else "idle"
    icon, title, detail = {
        "idle": ("○", "Проверка ещё не запускалась", "Запустите проверку, чтобы получить актуальный статус."),
        "ok": ("✓", "Система готова", "Критических проблем не обнаружено."),
        "warn": ("!", "Нужно внимание", "Есть предупреждения, работа системы не заблокирована."),
        "err": ("×", "Есть ошибки", "Откройте детали проверки и технический журнал."),
    }[safe_status]
    return (
        f'<div class="sov-config-readiness sov-config-readiness--{safe_status}" '
        'role="status" aria-live="polite">'
        f'  <span class="sov-config-readiness__mark" aria-hidden="true">{icon}</span>'
        '  <div class="sov-config-readiness__copy">'
        f'    <div class="sov-config-readiness__title">{title}</div>'
        f'    <div class="sov-config-readiness__detail">{detail}</div>'
        '</div>'
        '</div>'
    )


def _build_diag_metric(label: str, value: str = "—", *, tone: str = "muted"):
    """Строит компактную строку показателя внутри единого status strip."""
    with ui.element("div").classes(
        f"sov-config-metric sov-config-metric--{tone}"
    ):
        value_label = ui.label(value).classes("sov-config-metric__value")
        ui.label(label).classes("sov-config-metric__label")
    return value_label


def _build_acronym_glossary_html() -> str:
    """Возвращает компактный словарь системных сокращений."""
    items = [
        ("Л.Е.С.", "Локальная Единая Система", "ядро и рабочий контур"),
        ("С.О.В.У.Ш.К.А.", "Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная", "интерфейс"),
        ("С.А.М.О.В.А.Р.", "Система Автономной Машинной Обработки Внутренних Архивов RAG", "индекс знаний"),
        ("П.Р.О.Р.А.Б.", "Программа Регулярной Оценки Работы Автономной Базы", "метрики"),
        ("Д.И.А.Г.Н.О.З.", "Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья", "проверки"),
        ("Т.О.С.К.А.", "Терминал Оценки, Самопроверки и Контроля Архитектуры", "валидация"),
        ("В.О.Л.К.", "Внутренний Охранный Локальный Контур", "доступ"),
        ("Е.Ж.И.К.", "Единый Журнал Импорта Корреспонденции", "почта (IMAP-сбор писем в RAG)"),
        ("С.У.Х.А.Р.И.К.", "Система Управления Холодными Архивами и Резервными Источниками Комплекса", "резервные копии"),
        ("П.А.У.К.", "Постоянный Активный Удалённый Канал", "сеть / туннель доступа (keepalive)"),
        ("К.О.Т.", "Классификатор Областей и Терминов", "таксономия доменов и синонимов"),
        ("RAG", "Retrieval-Augmented Generation", "ответ с поиском по источникам"),
        ("CRAG", "Corrective RAG", "контроль достоверности ответа"),
    ]
    if _is_windows():
        items.append(("Ollama", "Локальный runtime моделей", "генерация и эмбеддинги Windows"))
    else:
        items.append(("MLX", "Apple MLX / Metal runtime", "локальные модели"))
    cards = []
    for code, full, role in items:
        cards.append(
            '<div class="diag-acronym-item">'
            f'  <div class="diag-acronym-code">{esc(code)}</div>'
            f'  <div class="diag-acronym-full">{esc(full)}</div>'
            f'  <div class="diag-acronym-role">{esc(role)}</div>'
            '</div>'
        )
    return '<div class="diag-acronym-grid">' + "".join(cards) + "</div>"


def _normalize_diag_payload(payload: dict) -> dict:
    """Сглаживает старый контракт /api/diag под no-Docker runtime без рестарта proxy."""
    normalized = dict(payload or {})
    raw_checks = list((payload or {}).get("checks", []))
    mlx_health_ok = any(
        raw.get("name") == "MLX latency" and "MLX health OK" in str(raw.get("message", ""))
        for raw in raw_checks
    )
    checks = []
    for raw in raw_checks:
        item = dict(raw)
        name = item.get("name", "")
        value_msg = f"{item.get('value', '')} {item.get('message', '')}".lower()
        # БЕЗ маскировки: нормализация поясняет «not applicable / ещё нет данных», но raw_status хранит
        # исходный статус — иначе нельзя отличить «лениво грузится» от «сломан» (наблюдаемость врёт).
        docker_missing = (
            name == "Docker"
            and item.get("status") == "err"
            and ("no such file" in value_msg or "not found" in value_msg or "not running" in value_msg)
        )
        if docker_missing and not _is_windows():
            item.update(
                name="Docker runtime", status="ok", value="removed", expected="no Docker",
                message="не используется — Qdrant/proxy/UI/MLX работают через LaunchAgents",
            )
        elif name == "MLX Backend" and item.get("status") == "err" and mlx_health_ok:
            item.update(
                status="warn", raw_status="err", value="main idle", expected="health OK",
                message=f"MLX health отвечает, основная модель грузится лениво (исходно err: {item.get('message','')})".strip(),
            )
        elif (
            name == "Т.О.С.К.А. статистика"
            and item.get("status") == "err"
            and str(item.get("value", "")).startswith("V:0 N:0 H:0")
        ):
            item.update(
                status="warn", raw_status="err", expected="first validation sample",
                message="статистики валидации ещё нет (норма на старте)",
            )
        checks.append(item)

    ok_count = sum(1 for result in checks if result.get("status") == "ok")
    warn_count = sum(1 for result in checks if result.get("status") == "warn")
    err_count = sum(1 for result in checks if result.get("status") == "err")
    normalized.update(
        checks=checks,
        ok_count=ok_count,
        warn_count=warn_count,
        err_count=err_count,
        overall="ok" if err_count == 0 and warn_count <= 1 else ("warn" if err_count == 0 else "err"),
    )
    return normalized


def build_diag():
    """Строит содержимое вкладки Д.И.А.Г.Н.О.З. Вызывать внутри with ui.tab_panel(tab_diag)."""
    advanced_ui = {"colbert_preflight_ready": False, "colbert_active": False}
    with ui.column().classes("sov-config-page"):

        # ── Паспорт конфигурации ─────────────────
        with panel(variant="raised", classes="sov-config-hero"):
            with ui.row().classes("sov-config-hero__row"):
                with ui.column().classes("sov-config-hero__identity"):
                    ui.label("Конфигурация").classes("sov-config-eyebrow")
                    acronym_identity(
                        "Д.И.А.Г.Н.О.З.",
                        "Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья",
                        icon="o_health_and_safety",
                    )
                    ui.label(
                        "Проверка рабочих контуров Л.Е.С. без изменения данных и настроек."
                    ).classes("sov-config-intro")
                    diag_ts_lbl = ui.label("Последний прогон: —").classes(
                        "sov-config-last-run"
                    )
                with ui.row().classes("sov-config-hero__actions"):
                    diag_run_btn = action_button(
                        "Проверить систему",
                        icon="o_play_arrow",
                        on_click=lambda: asyncio.create_task(run_diag()),
                        variant="primary",
                        classes="sov-config-run",
                    )
                    action_button(
                        "Журнал",
                        icon="o_terminal",
                        on_click=lambda: _open_diag_log(),
                        variant="quiet",
                        compact=True,
                    )

            with ui.element("div").classes("sov-config-status-strip"):
                diag_overall = _html(_build_overall_status_html()).classes(
                    "sov-config-status-strip__overall"
                )
                with ui.element("div").classes("sov-config-status-strip__metrics"):
                    diag_ok_kpi = _build_diag_metric("Готово", tone="ok")
                    diag_warn_kpi = _build_diag_metric("Внимание", tone="warn")
                    diag_err_kpi = _build_diag_metric("Ошибки", tone="error")
                    diag_time_kpi = _build_diag_metric("Время, мс")

        # ── Рабочие контуры ──────────────────────
        with panel(variant="plain", classes="sov-config-section"):
            section_heading(
                "Рабочие контуры",
                "Статус сервисов после последней проверки. Серый статус означает, что проверка ещё не запускалась.",
            )
            diag_map = _html(_build_diag_map_html([])).classes("w-full")

        with panel(variant="plain", classes="sov-config-section"):
            with ui.row().classes("w-full items-start justify-between gap-3"):
                section_heading(
                    "Контур RAG",
                    "Готовность каждой стадии активного поиска. Фактический путь запроса остаётся в trace ответа.",
                )
                rag_pipeline_overall = status_badge("Загрузка…", "muted")
            rag_pipeline_rows = ui.column().classes("w-full gap-2 q-mt-sm")

        with ui.expansion(
            "RAG · политика поиска",
            icon="o_account_tree",
        ).classes("sov-config-disclosure w-full"):
            section_heading(
                "RAPTOR и ColBERT",
                "Все факторы маршрута видны здесь. Adaptive пропускает дорогую стадию, если точного или дешёвого ответа уже достаточно.",
            )
            with ui.row().classes("w-full gap-3"):
                raptor_mode_select = select_field(
                    {"off": "Выключен", "adaptive": "Adaptive", "always": "Всегда"},
                    value="adaptive", label="RAPTOR", classes="grow",
                )
                colbert_mode_select = select_field(
                    {"off": "Выключен", "adaptive": "Adaptive", "always": "Всегда"},
                    value="adaptive", label="ColBERT", classes="grow",
                )
            with ui.row().classes("w-full gap-3"):
                colbert_candidates_input = ui.number(
                    "Кандидатов ColBERT", value=64, min=1, max=100000,
                ).classes("grow")
                colbert_output_input = ui.number(
                    "После ColBERT", value=32, min=1, max=100000,
                ).classes("grow")
                total_budget_input = ui.number(
                    "Общий бюджет, мс", value=2200, min=1, max=100000,
                ).classes("grow")
            with ui.row().classes("w-full gap-3"):
                raptor_fanout_input = ui.number(
                    "RAPTOR fanout", value=8, min=2, max=100,
                ).classes("grow")
                raptor_depth_input = ui.number(
                    "Глубина RAPTOR", value=3, min=1, max=10,
                ).classes("grow")
                raptor_route_k_input = ui.number(
                    "RAPTOR routes", value=8, min=1, max=1000,
                ).classes("grow")
                raptor_latency_input = ui.number(
                    "RAPTOR бюджет, мс", value=900, min=1, max=100000,
                ).classes("grow")
            with ui.row().classes("w-full gap-3"):
                raptor_summary_backend_select = select_field(
                    {"ollama": "Ollama · абстрактивно", "extractive": "Extractive · быстро"},
                    value="ollama", label="Резюме RAPTOR", classes="grow",
                )
                raptor_summary_model_input = text_field(
                    label="Модель резюме RAPTOR", value="qwen3.5:9b", classes="grow",
                )
                raptor_summary_url_input = text_field(
                    label="Локальный API резюме", value="http://127.0.0.1:11434", classes="grow",
                )
            with ui.row().classes("w-full gap-3"):
                raptor_summary_input_chars = ui.number(
                    "Вход резюме, символов", value=12000, min=256, max=100000,
                ).classes("grow")
                raptor_summary_max_chars = ui.number(
                    "Выход резюме, символов", value=1800, min=128, max=10000,
                ).classes("grow")
                colbert_passage_tokens_input = ui.number(
                    "Токенов ColBERT", value=128, min=8, max=1024,
                ).classes("grow")
                colbert_latency_input = ui.number(
                    "ColBERT бюджет, мс", value=700, min=1, max=100000,
                ).classes("grow")
            with ui.row().classes("w-full gap-3"):
                raptor_circuit_failures_input = ui.number(
                    "Ошибок до stop RAPTOR", value=3, min=1, max=100,
                ).classes("grow")
                raptor_circuit_cooldown_input = ui.number(
                    "Пауза RAPTOR, сек", value=180, min=1, max=86400,
                ).classes("grow")
                colbert_circuit_failures_input = ui.number(
                    "Ошибок до stop ColBERT", value=3, min=1, max=100,
                ).classes("grow")
                colbert_circuit_cooldown_input = ui.number(
                    "Пауза ColBERT, сек", value=300, min=1, max=86400,
                ).classes("grow")
            rag_advanced_status = ui.label("Загрузка…").classes("sov-ui-section-detail")
            rag_advanced_feedback = ui.column().classes("w-full")
            rag_advanced_runtime_rows = ui.column().classes("w-full gap-2")
            rag_advanced_preflight = ui.column().classes("w-full")
            with ui.row().classes("w-full gap-2"):
                rag_advanced_save_btn = action_button(
                    "Сохранить политику",
                    icon="o_save",
                    on_click=lambda: asyncio.create_task(save_rag_advanced()),
                    variant="secondary",
                )
                action_button(
                    "Проверить модели и место",
                    icon="o_fact_check",
                    on_click=lambda: asyncio.create_task(load_rag_preflight()),
                    variant="secondary",
                )
                raptor_build_btn = action_button(
                    "Построить / продолжить RAPTOR",
                    icon="o_account_tree",
                    on_click=lambda: asyncio.create_task(confirm_raptor_build()),
                    variant="danger",
                )
                colbert_build_btn = action_button(
                    "Построить ColBERT generation",
                    icon="o_storage",
                    on_click=lambda: asyncio.create_task(confirm_colbert_build()),
                    variant="danger",
                )
                colbert_build_btn.props("disabled")

        with ui.expansion(
            "Все параметры среды",
            icon="o_tune",
        ).classes("sov-config-disclosure w-full"):
            section_heading(
                "GUI-first реестр",
                "Показывает значение, источник и необходимость перезапуска. Секреты никогда не раскрываются. Опасные параметры отмечены Danger.",
            )
            runtime_registry_summary = ui.label("Загрузка…").classes("sov-ui-section-detail")
            runtime_registry_feedback = ui.column().classes("w-full")
            runtime_registry_rows = ui.column().classes("w-full gap-2")

        # Memory is an explicitly controlled adjacent module. Configuration is
        # persisted for the next controlled proxy start; this page never restarts it.
        with ui.expansion(
            "Память проектов",
            icon="o_psychology_alt",
        ).classes("sov-config-disclosure w-full"):
            section_heading(
                "Memory Core",
                "Накопленная память помогает навигации, но не заменяет RAG, источники или расчёт сметы.",
            )
            with ui.row().classes("w-full items-center gap-3"):
                memory_status_badge = status_badge("Загрузка…", "muted")
                memory_counts_label = ui.label("").classes("sov-ui-section-detail")
            with ui.row().classes("w-full gap-3"):
                memory_mode_select = select_field(
                    {"off": "Выключена", "shadow": "Только накопление", "on": "Включена"},
                    value="off",
                    label="Режим памяти",
                    classes="grow",
                )
                memory_recall_select = select_field(
                    {"off": "Не использовать", "advisory": "Подсказки", "route_reuse": "Маршруты смет (опасный)"},
                    value="off",
                    label="Память смет",
                    classes="grow",
                )
            memory_capture_switch = ui.switch(
                "Сохранять успешные опубликованные сметы", value=True
            ).props('aria-label="Сохранять успешные опубликованные сметы"')
            ui.label(
                "Переиспользование маршрутов не выбирает норму и включается только после отдельного подтверждения."
            ).classes("sov-ui-section-detail")
            memory_feedback = ui.column().classes("w-full")
            memory_save_btn = action_button(
                "Сохранить настройки",
                icon="o_save",
                on_click=lambda: asyncio.create_task(save_memory_config()),
                variant="secondary",
            )

        # ── Детали последней проверки ────────────
        with ui.expansion(
            "Детали последней проверки",
            icon="o_fact_check",
        ).classes("sov-config-disclosure w-full") as diag_details_expansion:
            ui.label(
                "Здесь появятся отдельные проверки, фактические значения и ожидаемое состояние."
            ).classes("sov-config-disclosure__intro")
            diag_cards = ui.column().classes("sov-config-checks")

        # ── С.У.Х.А.Р.И.К. Резервные копии ────────
        with ui.expansion(
            "С.У.Х.А.Р.И.К. · Резервные копии",
            icon="o_backup",
        ).classes("sov-config-disclosure w-full"):
            with ui.row().classes("sov-config-disclosure__header"):
                ui.label(
                    "Снапшоты Qdrant и SQLite-метабазы. Хранятся три последние копии."
                ).classes("sov-config-disclosure__intro")
                with ui.row().classes("sov-config-disclosure__actions"):
                    backup_create_btn = action_button(
                        "Создать копию",
                        icon="o_add_to_drive",
                        on_click=lambda: asyncio.create_task(create_backup()),
                        variant="secondary",
                        compact=True,
                    )
                    backup_restore_btn = action_button(
                        "Восстановить",
                        icon="o_restore",
                        on_click=lambda: asyncio.create_task(open_restore_dialog()),
                        variant="danger",
                        compact=True,
                    )
            backup_lists_el = ui.column().classes("sov-config-backups")

        # ── Термины ──────────────────────────────
        with ui.expansion(
            "Словарь системных сокращений",
            icon="o_menu_book",
        ).classes("sov-config-disclosure w-full"):
            ui.label(
                "Расшифровки модулей и служебных контуров Л.Е.С."
            ).classes("sov-config-disclosure__intro")
            _html(_build_acronym_glossary_html()).classes("w-full")

        # ── Технический журнал ───────────────────
        with ui.expansion(
            "Технический журнал",
            icon="o_terminal",
        ).classes("sov-config-disclosure w-full") as diag_log_expansion:
            ui.label(
                "Служебный вывод последнего прогона. Нужен для диагностики, а не для ежедневной работы."
            ).classes("sov-config-disclosure__intro")
            diag_log_el = ui.log(max_lines=80).classes(
                "sov-config-log w-full"
            )

    # ── Вспомогательные функции диагностики ──────────

    STATUS_ICON  = {"ok": "✓", "warn": "⚠", "err": "✗"}
    STATUS_COLOR = {"ok": "var(--ok)", "warn": "var(--warn)", "err": "var(--err)"}

    async def load_rag_pipeline():
        health = await api_get("/api/health")
        pipeline = ((health or {}).get("rag") or {}).get("retrieval_pipeline")
        rag_pipeline_rows.clear()
        if not isinstance(pipeline, dict):
            rag_pipeline_overall.set_text("Нет данных")
            with rag_pipeline_rows:
                render_feedback_state(
                    "error",
                    error_code="RAG_PIPELINE_STATUS_UNAVAILABLE",
                    detail="Прокси не вернул состояние стадий RAG.",
                )
            return

        overall = str(pipeline.get("status") or "unknown").lower()
        overall_text, _overall_tone = _pipeline_badge(overall)
        rag_pipeline_overall.set_text(overall_text)
        rag_pipeline_overall.classes(
            remove="sov-ui-status--ok sov-ui-status--warn sov-ui-status--error "
                   "sov-ui-status--blocked sov-ui-status--muted",
            add=f"sov-ui-status--{_overall_tone}",
        )
        stages = pipeline.get("stages") or {}
        with rag_pipeline_rows:
            for key, title in _RAG_PIPELINE_STAGE_LABELS.items():
                stage = stages.get(key) or {}
                status = str(stage.get("status") or "unknown").lower()
                badge_text, badge_tone = _pipeline_badge(status)
                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(title).classes("sov-ui-section-title")
                            ui.label(str(stage.get("detail") or "Нет данных")).classes(
                                "sov-ui-section-detail"
                            )
                        status_badge(badge_text, badge_tone)

    async def load_rag_advanced():
        payload = await api_get("/api/rag/advanced")
        rag_advanced_feedback.clear()
        rag_advanced_runtime_rows.clear()
        if not isinstance(payload, dict):
            rag_advanced_status.set_text("Политика недоступна")
            return
        policy = payload.get("policy") or {}
        status = payload.get("status") or {}
        raptor = policy.get("raptor") or {}
        colbert = policy.get("colbert") or {}
        execution = policy.get("execution") or {}
        raptor_mode_select.value = str(raptor.get("mode") or "adaptive")
        raptor_fanout_input.value = int(raptor.get("fanout") or 8)
        raptor_depth_input.value = int(raptor.get("max_depth") or 3)
        raptor_route_k_input.value = int(raptor.get("route_k") or 8)
        raptor_latency_input.value = int(raptor.get("latency_budget_ms") or 900)
        raptor_summary_backend_select.value = str(raptor.get("summary_backend") or "ollama")
        raptor_summary_model_input.value = str(raptor.get("summary_model") or "qwen3.5:9b")
        raptor_summary_url_input.value = str(
            raptor.get("summary_api_url") or "http://127.0.0.1:11434"
        )
        raptor_summary_input_chars.value = int(raptor.get("summary_input_chars") or 12000)
        raptor_summary_max_chars.value = int(raptor.get("summary_max_chars") or 1800)
        raptor_circuit_failures_input.value = int(raptor.get("circuit_breaker_failures") or 3)
        raptor_circuit_cooldown_input.value = int(
            raptor.get("circuit_breaker_cooldown_sec") or 180
        )
        colbert_mode_select.value = str(colbert.get("mode") or "adaptive")
        colbert_candidates_input.value = int(colbert.get("candidate_k") or 64)
        colbert_output_input.value = int(colbert.get("output_k") or 32)
        colbert_passage_tokens_input.value = int(colbert.get("max_passage_tokens") or 128)
        colbert_latency_input.value = int(colbert.get("latency_budget_ms") or 700)
        colbert_circuit_failures_input.value = int(colbert.get("circuit_breaker_failures") or 3)
        colbert_circuit_cooldown_input.value = int(
            colbert.get("circuit_breaker_cooldown_sec") or 300
        )
        total_budget_input.value = int(execution.get("total_latency_budget_ms") or 2200)
        raptor_runtime = status.get("raptor") or {}
        colbert_runtime = status.get("colbert") or {}
        rag_advanced_status.set_text(
            f"RAPTOR: {raptor_runtime.get('readiness', 'нет данных')} · "
            f"ColBERT: {colbert_runtime.get('readiness', 'нет данных')} · "
            f"ревизия {int(policy.get('revision') or 0)}"
        )
        raptor_active = str(raptor_runtime.get("readiness") or "") in {
            "queued", "building", "verifying"
        }
        if raptor_active:
            raptor_build_btn.props("disabled")
        else:
            raptor_build_btn.props(remove="disabled")
        colbert_active = str(colbert_runtime.get("readiness") or "") in {
            "queued", "building", "retrying", "verifying"
        }
        advanced_ui["colbert_active"] = colbert_active
        if colbert_active or not advanced_ui["colbert_preflight_ready"]:
            colbert_build_btn.props("disabled")
        else:
            colbert_build_btn.props(remove="disabled")
        with rag_advanced_runtime_rows:
            for title, runtime in (("RAPTOR", raptor_runtime), ("ColBERT", colbert_runtime)):
                readiness = str(runtime.get("readiness") or "not_built")
                badge_text, badge_tone = _pipeline_badge(
                    "indexing" if readiness in {"queued", "building", "verifying"}
                    else "ready" if readiness == "ready"
                    else "blocked" if readiness in {"blocked", "degraded"}
                    else "configured"
                )
                progress = round(float(runtime.get("progress") or 0) * 100)
                detail_parts = [f"прогресс {progress}%"]
                if runtime.get("documents_total"):
                    detail_parts.append(
                        f"документы {int(runtime.get('documents_completed') or 0)}/"
                        f"{int(runtime.get('documents_total') or 0)}"
                    )
                if runtime.get("published_nodes"):
                    detail_parts.append(f"узлы {int(runtime.get('published_nodes') or 0)}")
                detail_parts.append(f"circuit {runtime.get('circuit_state') or 'closed'}")
                if runtime.get("last_error_code"):
                    detail_parts.append(f"ошибка {runtime.get('last_error_code')}")
                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(title).classes("sov-ui-section-title")
                            ui.label(" · ".join(detail_parts)).classes("sov-ui-section-detail")
                        status_badge(badge_text, badge_tone)

    async def load_rag_preflight():
        payload = await api_get("/api/rag/advanced/preflight")
        rag_advanced_preflight.clear()
        with rag_advanced_preflight:
            if not isinstance(payload, dict):
                render_feedback_state(
                    "error",
                    error_code="RAG_ADVANCED_PREFLIGHT_UNAVAILABLE",
                    detail="Не удалось проверить модели и требуемое место.",
                )
                return
            colbert = payload.get("colbert") or {}
            raptor = payload.get("raptor") or {}
            storage = colbert.get("qdrant_multivector") or {}
            estimated_gb = float(storage.get("estimated_bytes") or 0) / (1024 ** 3)
            remaining_gb = float(
                ((colbert.get("model") or {}).get("download_remaining_bytes") or 0)
            ) / (1024 ** 3)
            with panel(variant="inset", classes="w-full"):
                section_heading(
                    "Preflight без загрузки модели",
                    "Проверка только читает метаданные cache и индекса; model_loaded=false.",
                )
                ui.label(
                    f"ColBERT: {colbert.get('status', 'unknown')} · "
                    f"индекс ≈ {estimated_gb:.2f} ГБ · догрузить модель ≈ {remaining_gb:.2f} ГБ"
                ).classes("sov-ui-section-detail")
                ui.label(
                    "Свободное место Docker: неизвестно — Qdrant API его не сообщает. "
                    "Это блокирующая ручная проверка перед тяжёлой сборкой."
                ).classes("sov-ui-section-detail")
                ui.label(
                    f"RAPTOR: ≈ {int(raptor.get('estimated_navigation_nodes') or 0)} узлов · "
                    f"модель {raptor.get('summary_model') or 'не задана'} · "
                    f"checkpoint {raptor.get('checkpoint_path') or 'не задан'}"
                ).classes("sov-ui-section-detail")
            blockers = colbert.get("blockers") or []
            advanced_ui["colbert_preflight_ready"] = not blockers
            if blockers or advanced_ui["colbert_active"]:
                colbert_build_btn.props("disabled")
            else:
                colbert_build_btn.props(remove="disabled")
                if blockers:
                    ui.label("Блокеры: " + ", ".join(str(item) for item in blockers)).classes(
                        "sov-ui-section-detail"
                    )

    async def confirm_raptor_build():
        with ui.dialog() as dialog, panel(variant="raised", classes="w-full"):
            section_heading(
                "Danger · построить RAPTOR",
                "Операция загрузит локальную модель резюме и создаст отдельный индекс. "
                "Evidence-коллекция не изменяется; прерванная работа продолжится с checkpoint.",
            )
            with ui.row().classes("w-full gap-2 justify-end"):
                action_button("Отмена", on_click=dialog.close, variant="quiet")
                action_button(
                    "Запустить",
                    icon="o_play_arrow",
                    on_click=lambda: asyncio.create_task(start_raptor_build(dialog)),
                    variant="danger",
                )
        dialog.open()

    async def start_raptor_build(dialog):
        dialog.close()
        result = await api_post("/api/rag/advanced/raptor/build", {})
        if result and result.get("status") == "queued":
            ui.notify("RAPTOR поставлен в очередь; прогресс сохраняется", type="warning")
            await load_rag_advanced()
        else:
            ui.notify("RAPTOR не запущен — проверьте статус и preflight", type="negative")

    async def confirm_colbert_build():
        with ui.dialog() as dialog, panel(variant="raised", classes="w-full"):
            section_heading(
                "Danger · построить ColBERT generation",
                "Будет создана полная sibling-коллекция dense+sparse+ColBERT. "
                "Активный индекс не меняется до прохождения readiness; затем alias переключится атомарно.",
            )
            ui.label(
                "Оценку диска и cache проверьте выше. Сбой продолжится с dataset-checkpoint; "
                "неполную коллекцию активировать нельзя."
            ).classes("sov-ui-section-detail")
            with ui.row().classes("w-full gap-2 justify-end"):
                action_button("Отмена", on_click=dialog.close, variant="quiet")
                action_button(
                    "Запустить генерацию",
                    icon="o_play_arrow",
                    on_click=lambda: asyncio.create_task(start_colbert_build(dialog)),
                    variant="danger",
                )
        dialog.open()

    async def start_colbert_build(dialog):
        dialog.close()
        result = await api_post("/api/rag/advanced/colbert/build", {})
        if result and result.get("status") == "queued":
            ui.notify("ColBERT generation поставлена в очередь", type="warning")
            await load_rag_advanced()
        else:
            ui.notify("ColBERT не запущен — устраните блокеры preflight", type="negative")

    async def save_rag_advanced():
        current = await api_get("/api/rag/advanced")
        if not isinstance(current, dict):
            ui.notify("Не удалось прочитать текущую политику RAG", type="negative")
            return
        policy = dict(current.get("policy") or {})
        policy["execution"] = dict(policy.get("execution") or {})
        policy["raptor"] = dict(policy.get("raptor") or {})
        policy["colbert"] = dict(policy.get("colbert") or {})
        policy["execution"]["total_latency_budget_ms"] = int(total_budget_input.value or 2200)
        policy["raptor"]["mode"] = str(raptor_mode_select.value or "adaptive")
        policy["raptor"]["fanout"] = int(raptor_fanout_input.value or 8)
        policy["raptor"]["max_depth"] = int(raptor_depth_input.value or 3)
        policy["raptor"]["route_k"] = int(raptor_route_k_input.value or 8)
        policy["raptor"]["latency_budget_ms"] = int(raptor_latency_input.value or 900)
        policy["raptor"]["summary_backend"] = str(
            raptor_summary_backend_select.value or "ollama"
        )
        policy["raptor"]["summary_model"] = str(raptor_summary_model_input.value or "")
        policy["raptor"]["summary_api_url"] = str(raptor_summary_url_input.value or "")
        policy["raptor"]["summary_input_chars"] = int(
            raptor_summary_input_chars.value or 12000
        )
        policy["raptor"]["summary_max_chars"] = int(
            raptor_summary_max_chars.value or 1800
        )
        policy["raptor"]["circuit_breaker_failures"] = int(
            raptor_circuit_failures_input.value or 3
        )
        policy["raptor"]["circuit_breaker_cooldown_sec"] = int(
            raptor_circuit_cooldown_input.value or 180
        )
        policy["colbert"]["mode"] = str(colbert_mode_select.value or "adaptive")
        policy["colbert"]["candidate_k"] = int(colbert_candidates_input.value or 64)
        policy["colbert"]["output_k"] = int(colbert_output_input.value or 32)
        policy["colbert"]["max_passage_tokens"] = int(
            colbert_passage_tokens_input.value or 128
        )
        policy["colbert"]["latency_budget_ms"] = int(colbert_latency_input.value or 700)
        policy["colbert"]["circuit_breaker_failures"] = int(
            colbert_circuit_failures_input.value or 3
        )
        policy["colbert"]["circuit_breaker_cooldown_sec"] = int(
            colbert_circuit_cooldown_input.value or 300
        )
        rag_advanced_save_btn.props("disabled")
        try:
            result = await api_put("/api/rag/advanced", policy)
            if result:
                ui.notify("Политика RAG сохранена", type="positive")
                await load_rag_advanced()
                await load_rag_pipeline()
            else:
                ui.notify("Политика RAG не сохранена", type="negative")
        finally:
            rag_advanced_save_btn.props(remove="disabled")

    async def load_runtime_registry():
        payload = await api_get("/api/settings/runtime-registry")
        runtime_registry_rows.clear()
        runtime_registry_feedback.clear()
        if not isinstance(payload, dict):
            runtime_registry_summary.set_text("Реестр недоступен")
            with runtime_registry_feedback:
                render_feedback_state(
                    "error", error_code="RUNTIME_CONFIG_REGISTRY_UNAVAILABLE",
                    detail="Не удалось получить полный список факторов.",
                )
            return
        counts = payload.get("counts") or {}
        runtime_registry_summary.set_text(
            f"Модель: {int(counts.get('effective') or 0)} · среда: {int(counts.get('total') or 0)} · "
            f"Danger: {int(counts.get('danger') or 0)} · "
            f"секретов: {int(counts.get('secrets') or 0)} · скрытых: {int(counts.get('unregistered') or 0)}"
        )
        with runtime_registry_rows:
            section_heading(
                "Фактический контекст модели",
                "Запрошенное значение, реально действующее ограничение и источник решения.",
            )
            for factor in payload.get("effective_factors") or []:
                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center gap-2"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(str(factor.get("label") or factor.get("id") or "Параметр")).classes(
                                "sov-ui-section-title"
                            )
                            ui.label(
                                "Запрошено: "
                                + _runtime_factor_value(factor.get("requested"))
                                + " → действует: "
                                + _runtime_factor_value(factor.get("effective"))
                            ).classes("sov-ui-section-detail")
                            detail = "Источник: " + _runtime_factor_source(
                                str(factor.get("source") or "unavailable")
                            )
                            if factor.get("restart_required"):
                                detail += " · нужен перезапуск"
                            ui.label(detail).classes("sov-ui-section-detail")
                            if factor.get("operator_action") == "profile_clone":
                                ui.label(
                                    "Изменение — только через копию профиля."
                                ).classes("sov-ui-section-detail")
                        status_badge("Только чтение", "muted")
            ui.separator()
            section_heading(
                "Переменные среды",
                "Технические значения runtime; секреты показываются только как заданные или незаданные.",
            )
            for factor in payload.get("factors") or []:
                key = str(factor.get("key") or "")
                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center gap-2"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(key).classes("sov-ui-section-title")
                            detail = f"Источник: {factor.get('source', 'default')}"
                            if factor.get("restart_required"):
                                detail += " · нужен перезапуск"
                            ui.label(detail).classes("sov-ui-section-detail")
                        if factor.get("danger"):
                            status_badge("Danger", "error")
                        elif factor.get("secret"):
                            status_badge("Секрет", "muted")
                    field = ui.input(
                        value="" if factor.get("secret") else str(factor.get("display_value") or ""),
                        placeholder="Задать новое значение" if factor.get("secret") else "",
                        password=bool(factor.get("secret")),
                    ).classes("w-full")
                    if not factor.get("mutable"):
                        field.props("readonly")
                    else:
                        action_button(
                            "Сохранить",
                            icon="o_save",
                            on_click=lambda _, item=factor, control=field: asyncio.create_task(
                                save_runtime_factor(item, control)
                            ),
                            variant="danger" if factor.get("danger") else "quiet",
                            compact=True,
                        )

    async def save_runtime_factor(factor: dict, control):
        key = str(factor.get("key") or "")
        value = str(control.value or "")
        confirmations: list[str] = []
        if factor.get("danger"):
            with ui.dialog() as dialog, panel(variant="raised", classes="q-pa-md"):
                section_heading(
                    f"Danger · {key}",
                    "Изменение может нарушить безопасность или стабильность. Перед записью будет создана резервная копия.",
                )
                with ui.row().classes("justify-end gap-2"):
                    action_button("Отмена", on_click=lambda: dialog.submit(False), variant="quiet")
                    action_button("Понимаю риск", on_click=lambda: dialog.submit(True), variant="danger")
            dialog.open()
            if not await dialog:
                return
            confirmations.append(key)
        result = await api_put(
            "/api/settings/runtime-registry",
            {"updates": {key: value}, "danger_confirmations": confirmations},
        )
        if result:
            ui.notify("Параметр сохранён", type="positive")
            await load_runtime_registry()
        else:
            ui.notify("Параметр не сохранён", type="negative")

    async def load_memory_config():
        payload = await api_get("/api/memory/status")
        memory_feedback.clear()
        if not isinstance(payload, dict):
            memory_status_badge.set_text("Недоступна")
            with memory_feedback:
                render_feedback_state("error", detail="Не удалось прочитать настройки Memory Core.")
            return
        mode = str(payload.get("mode") or "off")
        memory_mode_select.value = mode
        memory_recall_select.value = str(payload.get("smeta_recall_mode") or "off")
        memory_capture_switch.value = bool(payload.get("smeta_capture_enabled", True))
        memory_status_badge.set_text({"off": "Выключена", "shadow": "Накопление", "on": "Включена"}.get(mode, mode))
        memory_counts_label.set_text(
            f"Трасс смет: {int(payload.get('smeta_traces') or 0)} · конфликтов: {int(payload.get('open_conflicts') or 0)}"
        )

    async def save_memory_config():
        mode = str(memory_mode_select.value or "off")
        recall = str(memory_recall_select.value or "off")
        if mode != "on" and recall != "off":
            ui.notify("Подсказки памяти доступны только в режиме «Включена».", type="warning")
            return
        if recall == "route_reuse":
            with ui.dialog() as dialog, panel(variant="raised", classes="q-pa-md"):
                section_heading(
                    "Подтвердите переиспользование маршрутов",
                    "Memory передаст модели только путь каталога. Норму, применимость и расчёт модель проверит заново.",
                )
                with ui.row().classes("justify-end gap-2"):
                    action_button("Отмена", on_click=lambda: dialog.submit(False), variant="quiet")
                    action_button("Подтверждаю", on_click=lambda: dialog.submit(True), variant="danger")
            dialog.open()
            if not await dialog:
                return
        memory_save_btn.props("disabled")
        try:
            result = await api_put("/api/memory/config", {
                "mode": mode,
                "smeta_capture": bool(memory_capture_switch.value),
                "smeta_recall": recall,
            })
            memory_feedback.clear()
            with memory_feedback:
                if result:
                    ui.label(
                        "Настройки сохранены. Они применятся после штатного перезапуска Л.Е.С."
                    ).classes("sov-ui-section-detail")
                else:
                    render_feedback_state("error", detail="Настройки не сохранены.")
        finally:
            memory_save_btn.props(remove="disabled")

    async def load_backups():
        data = await api_get("/api/backup/status")
        backup_lists_el.clear()
        if not data:
            with backup_lists_el:
                ui.label("Не удалось загрузить статус бэкапов").style("color:var(--err);font-size:.75rem;")
            return

        sqlite_backups = data.get("sqlite_backups", [])
        qdrant_snapshots = data.get("qdrant_snapshots", [])
        profile = data.get("profile", "unknown")
        collection = data.get("collection_name", "unknown")

        with backup_lists_el:
            with ui.row().classes("w-full gap-3"):
                # Столбец SQLite
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(f"SQLite Метабаза ({profile})").style("font-size:.75rem;font-weight:900;color:var(--accent);")
                    if not sqlite_backups:
                        ui.label("Нет доступных копий SQLite").style("font-size:.7rem;color:var(--dim);")
                    for b in sqlite_backups:
                        size_mb = b['size_bytes'] / (1024 * 1024)
                        dt = b['created_at'].split('.')[0].replace('T', ' ')
                        with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                            "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                        ):
                            with ui.column().classes("gap-0"):
                                ui.label(b['name']).style("font-size:.7rem;font-weight:700;color:var(--text);")
                                ui.label(f"{size_mb:.1f} MB | {dt}").style("font-size:.6rem;color:var(--dim);")
                            ui.button(
                                "✗",
                                on_click=lambda _, name=b['name']: asyncio.create_task(delete_backup_item("sqlite", name))
                            ).props("flat dense").style("color:var(--err);font-weight:900;")

                # Столбец Qdrant
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(f"Qdrant Снапшоты ({collection})").style("font-size:.75rem;font-weight:900;color:var(--accent);")
                    if not qdrant_snapshots:
                        ui.label("Нет доступных снапшотов Qdrant").style("font-size:.7rem;color:var(--dim);")
                    for s in qdrant_snapshots:
                        size_mb = s['size_bytes'] / (1024 * 1024)
                        dt = s['created_at'].split('.')[0].replace('T', ' ')
                        with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                            "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                        ):
                            with ui.column().classes("gap-0"):
                                ui.label(s['name']).style("font-size:.7rem;font-weight:700;color:var(--text);")
                                ui.label(f"{size_mb:.1f} MB | {dt}").style("font-size:.6rem;color:var(--dim);")
                            ui.button(
                                "✗",
                                on_click=lambda _, name=s['name']: asyncio.create_task(delete_backup_item("qdrant", name))
                            ).props("flat dense").style("color:var(--err);font-weight:900;")

    async def create_backup():
        backup_create_btn.props("disabled")
        backup_create_btn.set_text("Создание…")
        ui.notify("Запущено создание резервной копии SQLite & Qdrant...", type="info")
        res = await api_post("/api/backup/create")
        backup_create_btn.props(remove="disabled")
        backup_create_btn.set_text("Создать копию")
        if res:
            sqlite_ok = res.get("sqlite", {}).get("ok")
            qdrant_ok = res.get("qdrant", {}).get("ok")
            if sqlite_ok and qdrant_ok:
                ui.notify("Резервная копия SQLite и Qdrant успешно создана", type="positive")
            else:
                ui.notify("Создание бэкапа завершилось с ошибками", type="warning")
            await load_backups()
        else:
            ui.notify("Ошибка при создании резервной копии", type="negative")

    async def open_restore_dialog():
        data = await api_get("/api/backup/archives") or {}
        archives = data.get("archives", [])
        with ui.dialog() as dlg, ui.card().style(
            "background:var(--bg-panel);border:1px solid var(--border);min-width:480px;max-width:640px;max-height:74vh;padding:16px;"
        ):
            ui.label("Восстановление из архива").style("font-weight:900;font-size:.85rem;")
            ui.label("Перезапишет ЖИВОЙ индекс Qdrant и метабазу SQLite. .env не трогается. Сервис перезапустится.").style(
                "font-size:.64rem;color:var(--warn);line-height:1.4;margin-bottom:6px;"
            )
            if not archives:
                ui.label("Полных off-disk архивов нет (backup_runtime.sh → /Volumes/Data или storage/backups).").style(
                    "font-size:.66rem;color:var(--dim);"
                )
            with ui.scroll_area().style("max-height:48vh;width:100%;"):
                for a in archives:
                    gb = a.get("size_bytes", 0) / (1024 ** 3)
                    dt = str(a.get("created_at", "")).split(".")[0].replace("T", " ")
                    meta = (f"{gb:.1f} GB · {len(a.get('snapshots', []))} снапшотов"
                            + ("  · +SQLite" if a.get("has_sqlite") else "") + f" · {dt}")
                    with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                        "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                    ):
                        with ui.column().classes("gap-0"):
                            ui.label(a["name"]).style("font-size:.72rem;font-weight:700;color:var(--text);")
                            ui.label(meta).style("font-size:.6rem;color:var(--dim);")
                        ui.button("Восстановить",
                                  on_click=lambda _, p=a["path"], n=a["name"]: asyncio.create_task(confirm_restore(p, n, dlg))
                                  ).props("no-caps dense").style(
                            "background:rgba(245,181,74,.15);border:1px solid var(--warn);color:var(--warn);font-size:.66rem;"
                        )
            ui.button("Закрыть", on_click=dlg.close).props("flat dense no-caps").style("color:var(--dim);margin-top:6px;")
        dlg.open()

    async def confirm_restore(path: str, name: str, parent_dlg):
        with ui.dialog() as c, ui.card().style(
            "background:var(--bg-panel);border:1px solid var(--err);padding:16px;max-width:460px;"
        ):
            ui.label("Точно восстановить?").style("font-weight:900;color:var(--err);font-size:.8rem;")
            ui.label(f"Архив «{name}». ПЕРЕЗАПИШЕТ текущий индекс и метабазу. Прежняя метабаза сохранится "
                     "рядом как .pre_restore. Сервис перезапустится.").style(
                "font-size:.66rem;color:var(--text);line-height:1.4;"
            )
            with ui.row().classes("gap-2 justify-end w-full").style("margin-top:8px;"):
                ui.button("Отмена", on_click=c.close).props("flat dense no-caps").style("color:var(--dim);")
                ui.button("Восстановить", on_click=lambda: asyncio.create_task(do_restore(path, c, parent_dlg))
                          ).props("dense no-caps").style("background:var(--err);color:#fff;font-weight:700;font-size:.66rem;")
        c.open()

    async def do_restore(path: str, c, parent_dlg):
        c.close(); parent_dlg.close()
        res = await api_post("/api/backup/restore", {"archive_path": path})
        if res and res.get("status") == "launched":
            ui.notify(f"Восстановление запущено: {res.get('archive')}. Сервис перезапустится…", type="warning", timeout=10000)
        else:
            ui.notify("Не удалось запустить восстановление", type="negative")

    async def delete_backup_item(type_str: str, name: str):
        res = await api_post("/api/backup/delete", {"type": type_str, "name": name})
        if res and res.get("status") == "ok":
            ui.notify(f"Удалено успешно: {name}", type="positive")
            await load_backups()
        else:
            ui.notify(f"Ошибка при удалении {name}", type="negative")

    def _render_diag_cards():
        results = state.get("diag_results", [])
        diag_cards.clear()
        with diag_cards:
            for r in results:
                s = r["status"]
                label = {"ok": "Готово", "warn": "Внимание", "err": "Ошибка"}.get(
                    s, "Нет данных"
                )
                with ui.element("article").classes(
                    f"sov-config-check sov-config-check--{s}"
                ):
                    with ui.row().classes("sov-config-check__header"):
                        ui.label(r["name"]).classes("sov-config-check__name")
                        ui.label(label).classes("sov-config-check__status")
                    with ui.row().classes("sov-config-check__values"):
                        ui.label(r["value"]).classes("sov-config-check__value")
                        ui.label(f"Ожидалось: {r['expected']}").classes(
                            "sov-config-check__expected"
                        )
                    if r.get("message"):
                        ui.label(r["message"]).classes(
                            "sov-config-check__message"
                        )
                    ui.label(f"{r['latency_ms']} мс").classes(
                        "sov-config-check__latency"
                    )

    async def run_diag():
        if state["diag_running"]:
            ui.notify("Диагностика уже запущена", type="warning")
            return

        state["diag_running"] = True
        diag_run_btn.props("disabled")
        diag_run_btn.set_text("Проверка…")
        diag_log_el.clear()

        add_log("[DIAG] ▶ Запуск диагностики системы...")
        diag_log_el.push("> [С.О.В.У.Ш.К.А.] Запуск диагностики...")

        try:
            d = await api_get("/api/diag")

            if d is None:
                diag_log_el.push("> [WARN] /api/diag не найден — запуск встроенной диагностики")
                d = await _run_local_diag()
            else:
                d = _normalize_diag_payload(d)

            state["diag_results"] = d.get("checks", [])
            overall = d.get("overall", "warn")
            ok_c    = d.get("ok_count", 0)
            warn_c  = d.get("warn_count", 0)
            err_c   = d.get("err_count", 0)
            total_ms = d.get("total_ms", 0)
            ts      = d.get("timestamp", "—")

            diag_overall.set_content(_build_overall_status_html(overall))
            diag_ok_kpi.set_text(str(ok_c))
            diag_warn_kpi.set_text(str(warn_c))
            diag_err_kpi.set_text(str(err_c))
            diag_time_kpi.set_text(f"{total_ms:.0f}")
            diag_ts_lbl.set_text(f"Последний прогон: {ts}")

            _render_diag_cards()

            diag_map.set_content(_build_diag_map_html(state["diag_results"]))
            await load_rag_pipeline()

            for r in state["diag_results"]:
                icon = STATUS_ICON.get(r["status"], "?")
                line = (f"> [{icon}] {r['name']:30s}  "
                        f"{r['value']:25s}  {r['latency_ms']:6.1f}ms"
                        + (f"  ← {r['message']}" if r.get('message') else ""))
                diag_log_el.push(line)
                add_log(f"[DIAG] {icon} {r['name']}: {r['value']}")

            diag_log_el.push(
                f"> [═══] Итог: {ok_c}✓ {warn_c}⚠ {err_c}✗  "
                f"| Статус: {overall.upper()}  | Время: {total_ms:.0f} мс"
            )
            add_log(f"[DIAG] Завершено: {ok_c}✓ {warn_c}⚠ {err_c}✗ за {total_ms:.0f}мс")

        except Exception as ex:
            diag_log_el.push(f"> [ERR] Критическая ошибка диагностики: {ex}")
            add_log(f"[DIAG] ОШИБКА: {ex}")
        finally:
            state["diag_running"] = False
            diag_run_btn.props(remove="disabled")
            diag_run_btn.set_text("Проверить систему")

    async def _run_local_diag() -> dict:
        """Встроенная диагностика — имена чеков соответствуют карте в _build_diag_map_html."""
        results = []
        t0 = time.time()

        async def _chk(name, coro):
            t = time.time()
            try:
                status, value, expected, msg = await coro
            except Exception as e:
                status, value, expected, msg = "err", "exception", "—", str(e)
            ms = round((time.time() - t) * 1000, 1)
            results.append({"name": name, "status": status, "value": str(value),
                             "expected": str(expected), "message": msg, "latency_ms": ms})

        # ── Прокси (les-proxy) ──
        async def chk_proxy():
            r = await api_get("/api/health")
            ok = r is not None
            return ("ok" if ok else "err"), ("UP" if ok else "DOWN"), "UP", ""
        await _chk("les-proxy :8050", chk_proxy())

        # ── Активный локальный runtime моделей ──
        async def chk_local_model():
            provider = await active_llm_provider()
            if provider == "ollama":
                base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
                r = await api_get("/api/tags", base=base)
                if not isinstance(r, dict):
                    return "err", "DOWN", "UP", "Ollama недоступна"
                models = r.get("models") or []
                return "ok", f"Ollama · {len(models)} моделей", "UP", ""
            if provider != "mlx":
                return "warn", provider.upper(), "локальный runtime", "Проверка локальной модели не применяется"
            r = await api_get("/api/health", base=MLX_URL)
            if not r:
                return "err", "DOWN", "UP", "MLX Host недоступен"
            m = r.get("main_model") or r.get("model", "?")
            if isinstance(m, dict):
                model_name = m.get("path", "?")
                is_loaded = m.get("loaded", False)
            else:
                model_name = str(m)
                is_loaded = r.get("main_loaded", True)
            status = "ok" if is_loaded else "warn"
            val_str = f"{model_name} [{'LIVE' if is_loaded else 'IDLE'}]"
            return status, val_str, "LIVE", ""
        await _chk("Локальная модель", chk_local_model())

        # ── Qdrant — имя совпадает с node_map ──
        async def chk_qdrant():
            r = await api_get("/api/metrics")
            if not r:
                return "warn", "DOWN", "UP", "metrics недоступны"
            rag = r.get("rag", {})
            st = rag.get("status", "?")
            chunks = rag.get("chunks", 0)
            ok = st in ("ready", "ok")
            return ("ok" if ok else "warn"), f"{chunks} chunks / {st}", "ready", ""
        await _chk("Qdrant :6333", chk_qdrant())

        # ── Qdrant индекс ──
        async def chk_qdrant_idx():
            r = await api_get("/api/rag/datasets")
            if r is None:
                return "err", "—", "—", "datasets недоступны"
            indexed = [d for d in r if d.get("status") in ("INDEXED", "READY")]
            total = len(r)
            ok_flag = len(indexed) > 0
            return ("ok" if ok_flag else "warn"), f"{len(indexed)}/{total} indexed", "≥1", ""
        await _chk("Qdrant индекс", chk_qdrant_idx())

        # ── Загруженные модели активного runtime ──
        async def chk_loaded_models():
            provider = await active_llm_provider()
            if provider == "ollama":
                base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
                r = await api_get("/api/ps", base=base)
                if not isinstance(r, dict):
                    return "warn", "—", "runtime status", "Ollama status недоступен"
                models = r.get("models") or []
                return "ok", f"{len(models)} loaded", "0+ guarded", ""
            r = await api_get("/api/status")
            if not r:
                return "warn", "—", "status", "status недоступен"
            mlx = r.get("mlx", {})
            models = mlx.get("models", [])
            if models:
                return "ok", f"{len(models)} loaded", "0+ guarded", ""
            return "ok", "0 loaded", "0+ guarded", "Модели выгружены до запроса"
        await _chk("Загруженные модели", chk_loaded_models())

        # ── На Mac Docker не нужен; на Windows он является runtime Qdrant ──
        async def chk_runtime():
            if not _is_windows():
                return "ok", "LaunchAgents", "host services", "Docker не используется"
            r = await api_get("/api/metrics")
            rag = r.get("rag", {}) if isinstance(r, dict) else {}
            qdrant_status = str(rag.get("status") or "").lower()
            if qdrant_status in {"ready", "ok", "degraded", "empty", "not_indexed"}:
                return "ok", "Docker/Qdrant UP", "UP", ""
            return "warn", "не подтверждено", "Docker/Qdrant UP", "Проверьте Docker Desktop и Qdrant"
        await _chk("Docker runtime", chk_runtime())

        # ── RAM / CPU / Диск из метрик ──
        metrics_data = state.get("metrics", {})
        sys_m = metrics_data.get("system", {})

        async def chk_ram():
            ram_used = sys_m.get("ram_used", 0)
            ram_total = sys_m.get("ram_total", 24) or 24
            pct = ram_used / ram_total * 100
            if pct > 90:
                return "err", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<90%", "Критически мало RAM"
            if pct > 75:
                return "warn", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<75%", ""
            return "ok", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<75%", ""
        await _chk("RAM", chk_ram())

        async def chk_cpu():
            cpu = sys_m.get("cpu", 0)
            if cpu > 90:
                return "err", f"{cpu:.1f}%", "<90%", "Высокая нагрузка"
            if cpu > 70:
                return "warn", f"{cpu:.1f}%", "<70%", ""
            return "ok", f"{cpu:.1f}%", "<70%", ""
        await _chk("CPU", chk_cpu())

        async def chk_disk():
            du = sys_m.get("disk_used", 0)
            dt = sys_m.get("disk_total", 512) or 512
            pct = du / dt * 100
            if pct > 90:
                return "err", f"{du:.0f}/{dt:.0f} GB", "<90%", "Диск почти заполнен"
            if pct > 75:
                return "warn", f"{du:.0f}/{dt:.0f} GB", "<75%", ""
            return "ok", f"{du:.0f}/{dt:.0f} GB", "<75%", ""
        await _chk("Диск", chk_disk())

        # ── Сеть ──
        async def chk_net():
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as c:
                    resp = await c.get("https://api.ipify.org")
                    return "ok", "Доступна", "UP", ""
            except Exception as e:
                return "err", "Недоступна", "UP", str(e)
        await _chk("Сеть (интернет)", chk_net())

        total_ms = round((time.time() - t0) * 1000, 1)
        ok_c   = sum(1 for r in results if r["status"] == "ok")
        warn_c = sum(1 for r in results if r["status"] == "warn")
        err_c  = sum(1 for r in results if r["status"] == "err")
        overall = "ok" if err_c == 0 and warn_c <= 1 else ("warn" if err_c == 0 else "err")
        import time as _t
        return {
            "overall": overall, "ok_count": ok_c, "warn_count": warn_c,
            "err_count": err_c, "total_ms": total_ms,
            "timestamp": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            "checks": results,
        }

    def _open_diag_log():
        diag_log_el.clear()
        for line in state.get("logs", [])[-80:]:
            diag_log_el.push(line)
        diag_log_expansion.set_value(True)

    # Регистрируем initial-load callbacks только после определения всех nested
    # coroutine-функций. Это исключает гонку таймера с построением страницы.
    ui.timer(0.1, lambda: asyncio.create_task(load_backups()), once=True)
    ui.timer(0.1, lambda: asyncio.create_task(load_memory_config()), once=True)
    ui.timer(0.1, lambda: asyncio.create_task(load_rag_pipeline()), once=True)
    ui.timer(0.1, lambda: asyncio.create_task(load_rag_advanced()), once=True)
    ui.timer(0.2, lambda: asyncio.create_task(load_rag_preflight()), once=True)
    advanced_status_timer = ui.timer(3.0, lambda: asyncio.create_task(load_rag_advanced()))
    ui.timer(0.1, lambda: asyncio.create_task(load_runtime_registry()), once=True)
    return {"timers": [advanced_status_timer]}
