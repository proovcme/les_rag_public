"""
S.O.V.U.Sh.K.A. v5.0 - system map page.
"""
from __future__ import annotations

from nicegui import ui

from sovushka.state import state


SYSTEM_MAP = """%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, SFMono-Regular, Menlo", "primaryColor": "#162232", "primaryBorderColor": "#38bdf8", "primaryTextColor": "#f8fbff", "lineColor": "#7dd3fc", "tertiaryColor": "#0b1118"}}}%%
flowchart TB
    U[Пользователь] --> UI[С.О.В.У.Ш.К.А.<br/>чат / админка]
    UI --> P[les-proxy<br/>правила и API]
    P --> R{маршрут}
    R -->|нормы| Q[(Qdrant<br/>векторы)]
    R -->|таблицы| TBL[(Parquet<br/>строки)]
    Q --> CTX[контекст<br/>top chunks]
    TBL --> EXACT[точный расчет]
    CTX --> M[MLX Host<br/>Qwen]
    M --> V[Т.О.С.К.А.<br/>проверка]
    EXACT --> A[ответ<br/>с источником]
    V --> A
    A --> UI

    classDef edge fill:#101923,stroke:#38bdf8,color:#f8fbff,stroke-width:1.4px;
    classDef data fill:#10231d,stroke:#22e06f,color:#f8fbff;
    classDef model fill:#251a35,stroke:#c084fc,color:#f8fbff;
    classDef warn fill:#2b2312,stroke:#ffd166,color:#f8fbff;
    class UI,P,R,CTX,A edge;
    class Q,TBL data;
    class M,V model;
    class EXACT warn;"""


INDEXING_MAP = """%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, SFMono-Regular, Menlo", "primaryColor": "#162232", "primaryBorderColor": "#38bdf8", "primaryTextColor": "#f8fbff", "lineColor": "#7dd3fc", "tertiaryColor": "#0b1118"}}}%%
flowchart LR
    SRC[RAG_Content<br/>PDF DOCX XLSX] --> PLAN[smart-plan<br/>accepted/rejected]
    PLAN --> ROUTE[domain router<br/>NTD_* index]
    ROUTE --> DB[(SQLite<br/>files/chunks/jobs)]
    DB --> CONV[converter]
    CONV --> CHUNK[chunker<br/>1400 / 100]
    CHUNK --> EMB[Qwen3 Embedding<br/>1024d]
    EMB --> Q[(Qdrant<br/>upsert)]
    Q --> CHECK{points = chunks}
    CHECK -->|да| OK[готово]
    CHECK -->|нет| FIX[остановить<br/>и сверить]

    GUARD[memory guard<br/>batch=1] -.-> EMB
    JOB[qwen-index-until-done] -.-> PLAN

    classDef data fill:#10231d,stroke:#22e06f,color:#f8fbff;
    classDef work fill:#101923,stroke:#38bdf8,color:#f8fbff;
    classDef model fill:#251a35,stroke:#c084fc,color:#f8fbff;
    classDef stop fill:#351b1b,stroke:#ff6b6b,color:#f8fbff;
    class SRC,DB,Q data;
    class PLAN,ROUTE,CONV,CHUNK,CHECK,OK,JOB work;
    class EMB model;
    class GUARD,FIX stop;"""


RUNTIME_MAP = """%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, SFMono-Regular, Menlo", "primaryColor": "#162232", "primaryBorderColor": "#38bdf8", "primaryTextColor": "#f8fbff", "lineColor": "#7dd3fc", "tertiaryColor": "#0b1118"}}}%%
flowchart TB
    subgraph HOST[Mac Mini M4 / host launchd]
        Q[me.ovc.les.qdrant<br/>:6333]
        P[me.ovc.les.proxy<br/>:8050]
        U[com.les.sovushka<br/>:8051 / :8066]
        M[me.ovc.les.mlx<br/>:8080]
        I[me.ovc.les.qwen-index-until-done]
    end
    subgraph DATA[local data]
        QS[(data/qdrant)]
        SQL[(data/les_meta_qwen.db)]
        ST[(storage/datasets)]
    end
    subgraph EDGE[VPS edge]
        C[Caddy HTTPS]
        Z[ZeroTier route]
    end

    C --> Z --> U
    U --> P
    P --> Q
    P --> M
    I --> P
    Q --> QS
    P --> SQL
    P --> ST

    classDef svc fill:#101923,stroke:#38bdf8,color:#f8fbff;
    classDef data fill:#10231d,stroke:#22e06f,color:#f8fbff;
    classDef edge fill:#2b2312,stroke:#ffd166,color:#f8fbff;
    class Q,P,U,M,I svc;
    class QS,SQL,ST data;
    class C,Z edge;"""


AUTH_MAP = """%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, SFMono-Regular, Menlo", "primaryColor": "#162232", "primaryBorderColor": "#38bdf8", "primaryTextColor": "#f8fbff", "lineColor": "#7dd3fc", "tertiaryColor": "#0b1118"}}}%%
sequenceDiagram
    participant B as Browser
    participant UI as NiceGUI
    participant V as V.O.L.K.
    participant P as les-proxy
    participant DB as SQLite keys
    B->>UI: открыть / или /les
    UI->>V: trusted contour / key
    V->>DB: role lookup
    DB-->>V: admin или user
    V-->>UI: session role
    UI->>P: API request + auth headers
    P-->>UI: allowed response"""


TEMPLATES = {
    "Карта системы": SYSTEM_MAP,
    "Поток индексации": INDEXING_MAP,
    "Runtime": RUNTIME_MAP,
    "Доступ": AUTH_MAP,
}


def _shorten(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else f"{text[:limit - 1]}..."


def build_mermaid():
    """Build the system map page. Call inside tab_panel(tab_mermaid)."""
    initial_key = state.get("mermaid_template") or "Карта системы"
    initial_code = state.get("mermaid_last") or TEMPLATES.get(initial_key, SYSTEM_MAP)

    with ui.column().classes("les-map-page w-full"):
        with ui.row().classes("les-map-head w-full items-end justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("КАРТА Л.Е.С.").classes("les-map-title")
                ui.label("поток ответа · индексация · runtime · доступ").classes("les-map-subtitle")
            with ui.row().classes("gap-2 items-center"):
                ui.label("Mermaid").classes("tag-acc")
                ui.label("живой чертеж").classes("tag-ok")

        with ui.grid(columns="320px minmax(0, 1fr)").classes("les-map-layout w-full"):
            with ui.column().classes("les-map-rail gap-3"):
                ui.label("Срез").classes("section-title")
                selected_label = ui.label(initial_key).classes("les-map-selected")
                meta_label = ui.label("Смысловая карта текущего контура").classes("les-map-meta")

                with ui.column().classes("gap-2 w-full"):
                    template_buttons: dict[str, ui.button] = {}

                    def render(code: str, key: str | None = None) -> None:
                        state["mermaid_last"] = code
                        if key:
                            state["mermaid_template"] = key
                            selected_label.set_text(key)
                            meta_label.set_text(_shorten(META[key]))
                        editor.set_value(code)
                        mermaid_view.set_content(code)
                        for name, button in template_buttons.items():
                            if name == key:
                                button.classes(add="les-map-preset-active")
                            else:
                                button.classes(remove="les-map-preset-active")

                    for name, icon in (
                        ("Карта системы", "o_hub"),
                        ("Поток индексации", "o_sync_alt"),
                        ("Runtime", "o_dns"),
                        ("Доступ", "o_vpn_key"),
                    ):
                        button = ui.button(
                            name,
                            icon=icon,
                            on_click=lambda n=name: render(TEMPLATES[n], n),
                        ).props("no-caps unelevated align=left").classes("les-map-preset w-full")
                        template_buttons[name] = button

                with ui.row().classes("gap-2 w-full"):
                    ui.button(
                        "Отрисовать",
                        icon="o_play_arrow",
                        on_click=lambda: render(editor.value, None),
                    ).props("no-caps outline").classes("les-map-action")
                    ui.button(
                        "Сбросить",
                        icon="o_restore",
                        on_click=lambda: render(TEMPLATES[initial_key], initial_key),
                    ).props("no-caps flat").classes("les-map-action-muted")

                with ui.expansion("Исходник", icon="o_code", value=False).classes("les-map-source w-full"):
                    editor = ui.codemirror(
                        value=initial_code,
                        language="Markdown",
                        theme="vscodeDark",
                        line_wrapping=True,
                    ).classes("les-map-editor w-full")

            with ui.column().classes("les-map-preview-shell gap-3"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label("Схема").classes("section-title")
                    ui.label("no-Docker host runtime").classes("tag-dim")
                with ui.element("div").classes("les-map-preview"):
                    mermaid_view = ui.mermaid(initial_code).classes("les-map-mermaid")

        # Initial active button state after all closures have their widgets.
        for name, button in template_buttons.items():
            if name == initial_key:
                button.classes(add="les-map-preset-active")


META = {
    "Карта системы": "Запрос проходит через UI, proxy, retrieval, MLX и валидацию.",
    "Поток индексации": "Файлы идут через routing, chunking, embeddings и сверку Qdrant/SQLite.",
    "Runtime": "Сервисы живут на host LaunchAgents; Docker не участвует в штатном контуре.",
    "Доступ": "В.О.Л.К. назначает роль, proxy проверяет API-запросы.",
}
