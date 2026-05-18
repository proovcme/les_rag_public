"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка П.Р.О.Р.А.Б. (метрики узла)
"""
from __future__ import annotations

from nicegui import ui
from sovushka.state import state
from sovushka.components.charts import _html, pct_bar_html, format_bytes


def build_prorab():
    """Строит содержимое вкладки П.Р.О.Р.А.Б. Вызывать внутри with ui.tab_panel(tab_prorab)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("П.Р.О.Р.А.Б. // ДИАГНОСТИКА").style(
                "font-size:1rem;font-weight:900;letter-spacing:1px;"
            )
            ui.label("/api/metrics · /api/status · MLX :8080  [5–15s]").style(
                "font-size:.6rem;color:var(--dim);"
            )

        # KPI строка
        with ui.row().classes("w-full gap-3"):
            pro_kpi = {}
            for key, lbl, color in [
                ("files",  "Файлов",   "var(--text)"),
                ("chunks", "Чанков",   "var(--text)"),
                ("ram",    "RAM",      "var(--text)"),
                ("cpu",    "CPU",      "var(--text)"),
                ("queue",  "LLM Queue", "var(--ok)"),
            ]:
                with ui.card().classes("kpi-box flex-1"):
                    v = ui.label("—").style(f"font-size:1.6rem;font-weight:900;color:{color};")
                    ui.label(lbl).style(
                        "font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;"
                    )
                    pro_kpi[key] = v

        # Карточки метрик
        with ui.grid(columns=3).classes("w-full gap-3"):

            # RAM
            with ui.card().classes("card-les"):
                ui.label("RAM BREAKDOWN").classes("section-title mb-2")
                ram_bar = _html(pct_bar_html([
                    (50, "var(--ok)"), (50, "var(--border)")
                ]))
                with ui.row().classes("justify-between mt-1"):
                    ui.label("Sys").style("font-size:.6rem;color:var(--ok);")
                    ui.label("Free").style("font-size:.6rem;color:var(--dim);")
                ram_total_lbl = ui.label("— / — GB").style(
                    "font-size:.7rem;color:var(--dim);margin-top:4px;"
                )

            # Диск
            with ui.card().classes("card-les"):
                ui.label("ДИСК").classes("section-title mb-2")
                disk_bar = _html(pct_bar_html([(20, "var(--accent)"), (80, "var(--border)")]))
                disk_lbl = ui.label("— GB").style("font-size:.7rem;color:var(--dim);margin-top:4px;")

            # Т.О.С.К.А. v2
            with ui.card().classes("card-les"):
                ui.label("Т.О.С.К.А. v2").classes("section-title mb-2")
                crag_bar = _html(pct_bar_html([
                    (34, "var(--ok)"), (33, "var(--warn)"), (33, "var(--err)")
                ]))
                with ui.row().classes("justify-between mt-1"):
                    crag_v = ui.label("—% VERIF").style(
                        "font-size:.6rem;color:var(--ok);font-weight:700;"
                    )
                    crag_n = ui.label("—% N/D").style(
                        "font-size:.6rem;color:var(--warn);font-weight:700;"
                    )
                    crag_h = ui.label("—% HALL.").style(
                        "font-size:.6rem;color:var(--err);font-weight:700;"
                    )

            # Latency
            with ui.card().classes("card-les"):
                ui.label("LATENCY").classes("section-title mb-2")
                lat_lbl  = ui.label("— ms avg").style("font-size:1.2rem;font-weight:900;")
                ui.label("Search + Gen").style("font-size:.6rem;color:var(--dim);")

            # MLX Host
            with ui.card().classes("card-les col-span-2"):
                with ui.row().classes("items-center justify-between mb-2"):
                    ui.label("MLX HOST :8080").classes("section-title")
                    mlx_badge = _html('<span class="tag-dim">—</span>')
                mlx_models_container = ui.column().classes("gap-2 w-full")



            # Docker
            with ui.card().classes("card-les"):
                ui.label("DOCKER КОНТЕЙНЕРЫ").classes("section-title mb-2")
                docker_badge     = ui.label("—").style("font-size:.7rem;font-weight:700;")
                docker_container = ui.column().classes("gap-1 w-full")

            # Errors
            with ui.card().classes("card-les"):
                ui.label("HTTP ERRORS").classes("section-title mb-2")
                errors_lbl = ui.label("Нет ошибок").style("font-size:.7rem;color:var(--dim);")

        # ── Рендер метрик ──────────────────────────────────────────────────────

        def _n(v):
            """Извлекает path из MLX объекта {path, loaded}."""
            return v.get("path", str(v)) if isinstance(v, dict) else str(v or "")

        def _l(v, default=True):
            """Извлекает loaded из MLX объекта."""
            return v.get("loaded", default) if isinstance(v, dict) else default

        def _render_prorab():
            m   = state["metrics"]
            st  = state["status"]
            mlx = state["mlx_health"]
            s   = m.get("system", {})
            p   = m.get("pipeline", {})
            r   = m.get("rag", {})
            q   = m.get("queue", {})
            e   = m.get("errors", {})

            # KPI
            pro_kpi["files"].set_text(str(r.get("files", r.get("documents", 0))))
            pro_kpi["chunks"].set_text(str(r.get("chunks", 0)))
            pro_kpi["ram"].set_text(format_bytes(s.get("ram_used", 0)))
            pro_kpi["cpu"].set_text(f"{s.get('cpu',0):.1f}%")
            pro_kpi["queue"].set_text(str(q.get("llm_waiting", 0)))

            # RAM bar
            rt = s.get("ram_total", 24)
            ru = s.get("ram_used", 0)
            rf = max(0, rt - ru)
            ram_bar.set_content(pct_bar_html([
                (ru / rt * 100, "var(--ok)"),
                (rf / rt * 100, "var(--border)"),
            ]))
            ram_total_lbl.set_text(f"{ru:.1f} / {rt:.1f} GB")

            # Disk
            du  = s.get("disk_used", 0)
            dt_ = s.get("disk_total", 512) or 512
            dp  = du / dt_ * 100
            disk_bar.set_content(pct_bar_html([
                (dp, "var(--accent)"),
                (100 - dp, "var(--border)"),
            ]))
            disk_lbl.set_text(f"{du:.0f} / {dt_:.0f} GB")

            # CRAG v2
            cv = p.get("crag_verified_rate", p.get("crag_pass_rate", 0))
            cn = p.get("crag_nodata_rate", 0)
            ch = p.get("crag_halluc_rate", max(0, 1 - cv - cn))
            crag_bar.set_content(pct_bar_html([
                (cv * 100, "var(--ok)"),
                (cn * 100, "var(--warn)"),
                (ch * 100, "var(--err)"),
            ]))
            crag_v.set_text(f"{cv*100:.0f}% VERIF")
            crag_n.set_text(f"{cn*100:.0f}% N/D")
            crag_h.set_text(f"{ch*100:.0f}% HALL.")

            # Latency
            ls = p.get("latency_search", [])
            lg = p.get("latency_gen", [])
            if ls or lg:
                combined = [
                    (ls[i] if i < len(ls) else 0) + (lg[i] if i < len(lg) else 0)
                    for i in range(max(len(ls), len(lg)))
                ]
                avg = sum(combined) / len(combined) if combined else 0
                lat_lbl.set_text(f"{avg*1000:.0f} ms avg")

            # MLX Host
            if mlx:
                mlx_badge.set_content('<span class="tag-ok">UP</span>')
                engines = []
                if mlx.get("main_model") or mlx.get("model"):
                    mv = mlx.get("main_model") or mlx.get("model")
                    engines.append(("MAIN", _n(mv), _l(mv, True), "var(--accent)"))
                if mlx.get("val_model"):
                    engines.append(("VAL", _n(mlx["val_model"]), _l(mlx["val_model"], False), "var(--pauk)"))
                if mlx.get("embed_model") or mlx.get("embedding_model"):
                    ev = mlx.get("embed_model") or mlx.get("embedding_model")
                    engines.append(("EMBED", _n(ev) or "bge-m3", True, "var(--ok)"))

                mlx_models_container.clear()
                for label, name, loaded, color in engines:
                    with mlx_models_container:
                        with ui.row().classes("items-center justify-between w-full py-1").style(
                            "border-bottom:1px solid var(--border);"
                        ):
                            with ui.column().classes("gap-0"):
                                ui.label(name or "—").style(
                                    "font-size:.72rem;font-weight:700;color:var(--text);"
                                    "max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                                )
                                _html(f'<span class="tag-dim" style="color:{color};">{label}</span>')
                            _html(
                                f'<span class="{"tag-ok" if loaded else "tag-dim"}">'
                                f'{"LIVE" if loaded else "IDLE"}</span>'
                            )
            else:
                mlx_badge.set_content('<span class="tag-err">DOWN</span>')
                mlx_models_container.clear()
                with mlx_models_container:
                    ui.label("MLX Host недоступен").style("font-size:.7rem;color:var(--err);")



            # Docker
            containers = st.get("containers", [])
            all_ok = all(c.get("ok") for c in containers) if containers else False
            docker_badge.set_text(f"{len(containers)} UP" if all_ok else "ПРОБЛЕМА")
            docker_badge.style(f"color:{'var(--ok)' if all_ok else 'var(--err)'};")
            docker_container.clear()
            for c in containers:
                with docker_container:
                    with ui.row().classes("items-center justify-between py-1").style(
                        "border-bottom:1px solid var(--border);"
                    ):
                        ui.label(c["name"]).style("font-size:.72rem;font-weight:700;")
                        _html(
                            f'<span class="{"tag-ok" if c.get("ok") else "tag-err"}">'
                            f'{c.get("status","?").split()[0]}</span>'
                        )

            # Errors
            if e:
                errors_lbl.set_text(" | ".join(f"{k}: {v}" for k, v in e.items()))
                errors_lbl.style("color:var(--err);")
            else:
                errors_lbl.set_text("Нет ошибок")
                errors_lbl.style("color:var(--dim);")

        ui.timer(10, lambda: _render_prorab())  # синхронизован с bg_loop (10с)
        ui.timer(0.3, lambda: _render_prorab(), once=True)
