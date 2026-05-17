"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка ГРАФ / ДИАГРАММЫ
"""
from __future__ import annotations

from nicegui import ui
from sovushka.state import state


def build_mermaid():
    """Строит содержимое вкладки ГРАФ / ДИАГРАММЫ. Вызывать внутри with ui.tab_panel(tab_mermaid)."""
    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
        ui.label("ГРАФ / ДИАГРАММЫ").style("font-size:1rem;font-weight:900;letter-spacing:1px;")
        ui.label("Mermaid-генератор: редактируй код вручную или получай из AI ЧАТ").style(
            "font-size:.65rem;color:var(--dim);"
        )

        DEFAULT_MERMAID = """flowchart TD
    A([Запрос]) --> B{РАГ?}
    B -->|Да| C[Векторный поиск\nQdrant]
    B -->|Нет| D[LLM напрямую]
    C --> E[Контекст + промпт]
    E --> F[MLX Qwen3-14B]
    F --> G{Т.О.С.К.А.\nвалидация}
    G -->|VERIFIED| H([Ответ])
    G -->|NO_DATA| I([Нет данных])
    G -->|HALLUCINATION| J([Заблокировано])"""

        with ui.splitter(value=40).classes("w-full").style("height:500px;") as spl:
            with spl.before:
                with ui.column().classes("w-full h-full gap-2 p-2"):
                    ui.label("КОД ДИАГРАММЫ").classes("section-title")
                    mermaid_editor = ui.codemirror(
                        value=state.get("mermaid_last") or DEFAULT_MERMAID,
                        language="markdown",
                    ).classes("w-full flex-1").style(
                        "background:var(--bg-mod);border:1px solid var(--border);"
                        "border-radius:4px;font-size:.75rem;min-height:400px;"
                    )

                    with ui.row().classes("gap-2"):
                        def render_mermaid():
                            code = mermaid_editor.value
                            state["mermaid_last"] = code
                            mermaid_view.set_content(code)

                        ui.button("▶ Отрисовать", on_click=render_mermaid).props("no-caps outline").style(
                            "font-size:.7rem;border-color:var(--ok);color:var(--ok);"
                        )

                        templates = {
                            "Флоучарт Л.Е.С.": DEFAULT_MERMAID,
                            "Последовательность RAG": """sequenceDiagram
    participant U as Пользователь
    participant P as les-proxy
    participant Q as Qdrant
    participant M as MLX Host
    participant T as Т.О.С.К.А.
    U->>P: Запрос
    P->>Q: Векторный поиск
    Q-->>P: Топ-5 чанков
    P->>M: Промпт + контекст
    M-->>P: Ответ LLM
    P->>T: Валидация
    T-->>P: VERIFIED
    P-->>U: Ответ""",
                            "ER-диаграмма": """erDiagram
    DATASET {
        string id PK
        string name
        string status
        int chunk_count
    }
    SOURCE_FOLDER {
        string folder PK
        string dataset_id FK
        int source_files
        int indexed_files
    }
    JOB {
        string job_id PK
        string dataset_name FK
        string status
        int processed
        int total
    }
    DATASET ||--o{ SOURCE_FOLDER : "имеет"
    DATASET ||--o{ JOB : "запускает" """,
                        }
                        tmpl_select = ui.select(
                            list(templates.keys()),
                            label="Шаблон"
                        ).style("font-size:.7rem;flex:1;")

                        def load_template():
                            key = tmpl_select.value
                            if key and key in templates:
                                mermaid_editor.set_value(templates[key])
                                render_mermaid()

                        ui.button("Загрузить", on_click=load_template).props("no-caps flat").style(
                            "font-size:.7rem;color:var(--accent);"
                        )

            with spl.after:
                with ui.card().classes("card-les w-full h-full mermaid-wrap").style("overflow:auto;"):
                    ui.label("ПРЕВЬЮ").classes("section-title mb-3")
                    mermaid_view = ui.mermaid(state.get("mermaid_last") or DEFAULT_MERMAID)
