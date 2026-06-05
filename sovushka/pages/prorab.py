"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка П.Р.О.Р.А.Б. (метрики узла)
"""
from __future__ import annotations

import asyncio
from nicegui import context, ui
from sovushka.state import state, last_api_error_text
from sovushka.components.charts import _html, pct_bar_html, format_bytes, esc
from tools import les_runtime_control


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

        with ui.card().classes("card-les les-fuse-board w-full"):
            with ui.row().classes("items-center justify-between w-full gap-2"):
                with ui.column().classes("gap-0"):
                    ui.label("ПРЕДОХРАНИТЕЛИ").classes("section-title")
                    ui.label("runtime admission · memory · jobs · LLM slots").style(
                        "font-size:.6rem;color:var(--dim);"
                    )
                fuse_state = _html('<span class="tag-dim">SYNC</span>')
            fuse_reason = ui.label("Ожидаю телеметрию").style(
                "font-size:.72rem;color:var(--dim);overflow-wrap:anywhere;"
            )
            fuse_grid = _html('<div class="les-fuse-grid"></div>')

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
                    (25, "var(--ok)"), (25, "var(--warn)"), (25, "var(--err)"), (25, "var(--accent)")
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
                    crag_u = ui.label("—% OFF").style(
                        "font-size:.6rem;color:var(--accent);font-weight:700;"
                    )
                with ui.row().classes("justify-between mt-1"):
                    cache_rate_lbl = ui.label("CACHE —%").style(
                        "font-size:.56rem;color:var(--dim);font-weight:700;"
                    )
                    retrieval_rate_lbl = ui.label("RET —%").style(
                        "font-size:.56rem;color:var(--dim);font-weight:700;"
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
                    with ui.row().classes("items-center gap-2"):
                        mlx_badge = _html('<span class="tag-dim">—</span>')
                        warmup_btn = ui.button(
                            "⚡ ПРОГРЕВ", on_click=lambda: asyncio.create_task(_warmup())
                        ).props("no-caps outline dense").style(
                            "font-size:.6rem;color:var(--warn);border-color:var(--warn);"
                            "padding:2px 8px;"
                        )
                mlx_models_container = ui.column().classes("gap-2 w-full")



            # Host runtime
            with ui.card().classes("card-les"):
                ui.label("HOST RUNTIME").classes("section-title mb-2")
                runtime_badge = ui.label("LAUNCHD").style("font-size:.7rem;font-weight:700;color:var(--ok);")
                runtime_container = ui.column().classes("gap-1 w-full")

            # Errors
            with ui.card().classes("card-les"):
                ui.label("HTTP ERRORS").classes("section-title mb-2")
                errors_lbl = ui.label("Нет ошибок").style("font-size:.7rem;color:var(--dim);")

        # Аварийное управление launchd не зависит от les-proxy.
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full mb-2"):
                with ui.column().classes("gap-0"):
                    ui.label("АВАРИЙНОЕ УПРАВЛЕНИЕ").classes("section-title")
                    ui.label("локальный launchd: Qdrant · MLX · proxy · indexer · UI").style(
                        "font-size:.6rem;color:var(--dim);"
                    )
                runtime_refresh_btn = ui.button(
                    "↻ ОБНОВИТЬ", on_click=lambda: asyncio.create_task(_refresh_runtime_ops())
                ).props("no-caps outline dense").style(
                    "font-size:.6rem;color:var(--accent);border-color:var(--accent);"
                )
            runtime_ops_grid = ui.grid(columns=5).classes("w-full gap-2")
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.button(
                    "▶ ПОДНЯТЬ КОНТУР",
                    on_click=lambda: asyncio.create_task(_runtime_action("start_core")),
                ).props("no-caps dense").style(
                    "font-size:.62rem;background:rgba(34,224,111,.14);color:var(--ok);"
                    "border:1px solid var(--ok);"
                )
                ui.button(
                    "■ СТОП КОНТУР",
                    on_click=lambda: asyncio.create_task(_runtime_action("stop_core")),
                ).props("no-caps dense outline").style(
                    "font-size:.62rem;color:var(--err);border-color:var(--err);"
                )
                ui.button(
                    "↻ PROXY",
                    on_click=lambda: asyncio.create_task(_runtime_action("restart_proxy")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--accent);")
                ui.button(
                    "↻ MLX",
                    on_click=lambda: asyncio.create_task(_runtime_action("restart_mlx")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--warn);")
                ui.button(
                    "↻ QDRANT",
                    on_click=lambda: asyncio.create_task(_runtime_action("restart_qdrant")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--accent);")
                ui.button(
                    "▶ INDEX",
                    on_click=lambda: asyncio.create_task(_runtime_action("start_indexer")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--ok);")
                ui.button(
                    "■ INDEX",
                    on_click=lambda: asyncio.create_task(_runtime_action("stop_indexer")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--warn);")
                ui.button(
                    "↻ UI",
                    on_click=lambda: asyncio.create_task(_runtime_action("restart_ui")),
                ).props("no-caps dense outline").style("font-size:.62rem;color:var(--dim);")
            runtime_ops_log = ui.log(max_lines=18).classes("w-full").style(
                "background:var(--bg);color:var(--ok);font-family:var(--font);"
                "font-size:.62rem;height:86px;border:1px solid var(--border);margin-top:8px;"
            )

        # ── Вспомогательные действия ───────────────────────────────────────────

        async def _warmup():
            warmup_btn.props("loading")
            warmup_btn.set_text("...")
            from sovushka.state import api_post, add_log
            add_log("[MLX] Прогрев моделей...")
            d = await api_post("/api/warmup")
            warmup_btn.props(remove="loading")
            if d and d.get("status") == "done":
                models = d.get("models", {})
                main_t = models.get("main", {}).get("elapsed", "?")
                val_t  = models.get("val",  {}).get("elapsed", "?")
                ui.notify(f"✓ Прогрев OK: main {main_t}с, val {val_t}с", type="positive")
                add_log(f"[MLX] Прогрев завершён: main={main_t}с val={val_t}с")
                warmup_btn.set_text("✓ OK")
            else:
                ui.notify(last_api_error_text("Ошибка прогрева — проверь логи"), type="negative")
                warmup_btn.set_text("⚡ ПРОГРЕВ")

        def _render_runtime_ops(statuses):
            runtime_ops_grid.clear()
            with runtime_ops_grid:
                for item in statuses:
                    cls = "tag-ok" if item.running else "tag-err"
                    health_cls = (
                        "tag-ok" if item.health == "ok"
                        else "tag-warn" if item.health in {"n/a", "slow"}
                        else "tag-err"
                    )
                    pid = item.pid or item.port_pid or "—"
                    port = f":{item.port}" if item.port else "launchd"
                    with ui.card().classes("les-runtime-service"):
                        with ui.row().classes("items-center justify-between w-full"):
                            ui.label(item.title).style("font-size:.68rem;font-weight:900;color:var(--text);")
                            _html(f'<span class="{cls}">{"UP" if item.running else "DOWN"}</span>')
                        ui.label(port).style("font-size:.58rem;color:var(--dim);")
                        with ui.row().classes("items-center justify-between w-full"):
                            ui.label(f"pid {pid}").style("font-size:.56rem;color:var(--dim);")
                            _html(f'<span class="{health_cls}">{esc(item.health.upper())}</span>')
                        if item.detail:
                            ui.label(item.detail[:60]).style(
                                "font-size:.52rem;color:var(--dim);"
                                "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
                            )

        async def _refresh_runtime_ops():
            runtime_refresh_btn.props("loading")
            try:
                statuses = await asyncio.to_thread(
                    les_runtime_control.all_statuses,
                    ["qdrant", "proxy", "mlx", "indexer", "ui"],
                )
                _render_runtime_ops(statuses)
            finally:
                runtime_refresh_btn.props(remove="loading")

        def _push_runtime_result(result):
            mark = "✓" if result.ok else "✗"
            runtime_ops_log.push(f"> [{mark}] {result.action} {result.service}: {result.message}")
            if result.stderr:
                runtime_ops_log.push(f"> stderr: {result.stderr.strip()[:180]}")

        async def _runtime_action(action: str):
            from sovushka.state import add_log
            runtime_ops_log.push(f"> [..] {action}")
            add_log(f"[RUNTIME] {action}")
            if action == "start_core":
                results = await asyncio.to_thread(les_runtime_control.start_core, False, True)
            elif action == "stop_core":
                results = await asyncio.to_thread(les_runtime_control.stop_core, False)
            elif action == "restart_proxy":
                results = [await asyncio.to_thread(les_runtime_control.restart_service, "proxy")]
            elif action == "restart_mlx":
                results = [await asyncio.to_thread(les_runtime_control.restart_service, "mlx")]
            elif action == "restart_qdrant":
                results = [await asyncio.to_thread(les_runtime_control.restart_service, "qdrant")]
            elif action == "start_indexer":
                results = [await asyncio.to_thread(les_runtime_control.start_service, "indexer")]
            elif action == "stop_indexer":
                results = [await asyncio.to_thread(les_runtime_control.stop_service, "indexer")]
            elif action == "restart_ui":
                ui.notify("UI перезапускается; страница переподключится", type="warning")
                await asyncio.to_thread(les_runtime_control.restart_service, "ui", False)
                return
            else:
                ui.notify(f"Неизвестное действие: {action}", type="negative")
                return

            for result in results:
                _push_runtime_result(result)
            ok = all(result.ok for result in results)
            ui.notify("Готово" if ok else "Есть предупреждения, смотри лог", type="positive" if ok else "warning")
            await _refresh_runtime_ops()

        # ── Рендер метрик ──────────────────────────────────────────────────────

        def _n(v):
            """Извлекает path из MLX объекта {path, loaded}."""
            return v.get("path", str(v)) if isinstance(v, dict) else str(v or "")

        def _l(v, default=True):
            """Извлекает loaded из MLX объекта."""
            return v.get("loaded", default) if isinstance(v, dict) else default

        def _fuse_level(ok: bool, warn: bool = False) -> str:
            if ok:
                return "ok"
            return "warn" if warn else "err"

        def _fuse_item(label: str, value: str, detail: str, level: str) -> str:
            return (
                f'<div class="les-fuse les-fuse-{level}">'
                f'<div class="les-fuse-cap">{esc(label)}</div>'
                f'<div class="les-fuse-val">{esc(value)}</div>'
                f'<div class="les-fuse-detail">{esc(detail)}</div>'
                f'</div>'
            )

        def _render_fuses(status_data: dict, metrics_data: dict):
            admission = status_data.get("chat_admission") if isinstance(status_data.get("chat_admission"), dict) else {}
            mode = status_data.get("mode") if isinstance(status_data.get("mode"), dict) else {}
            pressure = status_data.get("memory_state") if isinstance(status_data.get("memory_state"), dict) else {}
            system = metrics_data.get("system") if isinstance(metrics_data.get("system"), dict) else {}
            queue = metrics_data.get("queue") if isinstance(metrics_data.get("queue"), dict) else {}

            allowed = bool(admission.get("allowed", True))
            reason = str(admission.get("reason") or "chat generation allowed")
            memory = admission.get("memory") if isinstance(admission.get("memory"), dict) else {}
            ram_free = memory.get("ram_free_gb", system.get("ram_free_gb"))
            swap_pct = memory.get("swap_pct", system.get("swap_pct"))
            active_jobs = admission.get("active_jobs", 0)
            llm_waiting = queue.get("llm_waiting", 0)
            profile_name = str(admission.get("runtime_profile") or status_data.get("runtime_profile") or "CHAT").upper()
            memory_state = str(admission.get("memory_state") or pressure.get("state") or "UNKNOWN").upper()

            state_cls = "tag-ok" if allowed else "tag-err"
            state_text = "SHIELD OPEN" if allowed else "SHIELD LOCKED"
            fuse_state.set_content(f'<span class="{state_cls}">{state_text}</span>')
            fuse_reason.set_text(reason)
            fuse_reason.style(f"font-size:.72rem;color:{'var(--ok)' if allowed else 'var(--warn)'};overflow-wrap:anywhere;")

            try:
                ram_free_f = float(ram_free)
            except (TypeError, ValueError):
                ram_free_f = 0.0
            try:
                swap_f = float(swap_pct)
            except (TypeError, ValueError):
                swap_f = 100.0
            try:
                active_jobs_i = int(active_jobs or 0)
            except (TypeError, ValueError):
                active_jobs_i = 0
            try:
                llm_waiting_i = int(llm_waiting or 0)
            except (TypeError, ValueError):
                llm_waiting_i = 0

            mode_ok = profile_name in {"CHAT", "CHAT_VALIDATED"}
            ram_ok = ram_free_f >= 8.0
            swap_ok = swap_f <= 60.0
            jobs_ok = active_jobs_i == 0
            llm_ok = llm_waiting_i == 0
            items = [
                _fuse_item("PROFILE", profile_name, "chat lane" if mode_ok else "guarded lane", _fuse_level(mode_ok)),
                _fuse_item("MEM STATE", memory_state, pressure.get("reason", ""), _fuse_level(memory_state in {"GREEN", "YELLOW"}, memory_state == "RED")),
                _fuse_item("RAM FREE", f"{ram_free_f:.1f} GB", "min 8.0 GB", _fuse_level(ram_ok, ram_free_f >= 6.0)),
                _fuse_item("SWAP", f"{swap_f:.1f}%", "max 60%", _fuse_level(swap_ok, swap_f <= 75.0)),
                _fuse_item("JOBS", str(active_jobs_i), "active schedulers", _fuse_level(jobs_ok)),
                _fuse_item("LLM SLOT", "READY" if llm_ok else "BUSY", f"queue {llm_waiting_i}", _fuse_level(llm_ok, llm_waiting_i <= 1)),
            ]
            fuse_grid.set_content('<div class="les-fuse-grid">' + "".join(items) + "</div>")

        _prev_render = {"mlx": None, "runtime": None}

        def _render_prorab():
          try:
            m   = state.get("metrics", {})
            st  = state.get("status", {})
            mlx = state.get("mlx_health", {})
            s   = m.get("system", {})
            p   = m.get("pipeline", {})
            r   = m.get("rag", {})
            q   = m.get("queue", {})
            e   = m.get("errors", {})

            _render_fuses(st, m)

            # KPI
            pro_kpi["files"].set_text(str(r.get("files", r.get("documents", 0))))
            pro_kpi["chunks"].set_text(str(r.get("chunks", 0)))
            pro_kpi["ram"].set_text(format_bytes(s.get("ram_used", 0)))
            pro_kpi["cpu"].set_text(f"{s.get('cpu',0):.1f}%")
            pro_kpi["queue"].set_text(str(q.get("llm_waiting", 0)))

            # RAM bar
            rt = s.get("ram_total", 24) or 24
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
            cu = p.get("crag_unvalidated_rate", 0)
            cache_rate = p.get("cache_hit_rate", 0)
            retrieval_rate = p.get("retrieval_good_rate", 0)
            crag_bar.set_content(pct_bar_html([
                (cv * 100, "var(--ok)"),
                (cn * 100, "var(--warn)"),
                (ch * 100, "var(--err)"),
                (cu * 100, "var(--accent)"),
            ]))
            crag_v.set_text(f"{cv*100:.0f}% VERIF")
            crag_n.set_text(f"{cn*100:.0f}% N/D")
            crag_h.set_text(f"{ch*100:.0f}% HALL.")
            crag_u.set_text(f"{cu*100:.0f}% OFF")
            cache_rate_lbl.set_text(f"CACHE {cache_rate*100:.0f}%")
            retrieval_rate_lbl.set_text(f"RET {retrieval_rate*100:.0f}%")

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

            # MLX Host — clear() только если данные изменились
            mlx_key = str(mlx)
            if mlx:
                mlx_badge.set_content('<span class="tag-ok">UP</span>')
                if mlx_key != _prev_render["mlx"]:
                    _prev_render["mlx"] = mlx_key
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
                if mlx_key != _prev_render["mlx"]:
                    _prev_render["mlx"] = mlx_key
                    mlx_badge.set_content('<span class="tag-err">DOWN</span>')
                    mlx_models_container.clear()
                    with mlx_models_container:
                        ui.label("MLX Host недоступен").style("font-size:.7rem;color:var(--err);")

            # Runtime — Docker intentionally removed; services run as host LaunchAgents.
            proxy = st.get("proxy", {})
            runtime_rows = [
                ("proxy", f":{proxy.get('port', 8050)}"),
                ("qdrant", ":6333"),
                ("mlx", ":8080"),
                ("ui", ":8051"),
            ]
            runtime_key = str(runtime_rows)
            if runtime_key != _prev_render["runtime"]:
                _prev_render["runtime"] = runtime_key
                runtime_badge.set_text("NO DOCKER")
                runtime_badge.style("color:var(--ok);")
                runtime_container.clear()
                for name, status in runtime_rows:
                    with runtime_container:
                        with ui.row().classes("items-center justify-between py-1").style(
                            "border-bottom:1px solid var(--border);"
                        ):
                            ui.label(name).style("font-size:.72rem;font-weight:700;")
                            _html(f'<span class="tag-ok">{status}</span>')

            # Errors
            if e:
                errors_lbl.set_text(" | ".join(f"{k}: {v}" for k, v in e.items()))
                errors_lbl.style("color:var(--err);")
            else:
                errors_lbl.set_text("Нет ошибок")
                errors_lbl.style("color:var(--dim);")
          except Exception as _ex:
              import logging
              logging.getLogger("les.prorab").warning(f"_render_prorab: {_ex}")

        prorab_timer = ui.timer(10, _render_prorab, active=True)
        context.client.on_disconnect(lambda *_: prorab_timer.cancel())
        _render_prorab()
        asyncio.create_task(_refresh_runtime_ops())
