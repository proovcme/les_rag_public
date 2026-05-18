"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка 🔬 ДИАГНОСТИКА
"""
from __future__ import annotations

import asyncio
import time
from nicegui import ui

from sovushka.state import state, api_get, add_log
from sovushka.config import MLX_URL
from sovushka.components.charts import _html


def build_diag():
    """Строит содержимое вкладки 🔬 ДИАГНОСТИКА. Вызывать внутри with ui.tab_panel(tab_diag)."""
    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):

        # ── Заголовок и кнопка ──────────────────
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label("🔬 ДИАГНОСТИКА СИСТЕМЫ").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;"
                )
                diag_ts_lbl = ui.label("Последний прогон: —").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            with ui.row().classes("gap-2"):
                diag_run_btn = ui.button(
                    "▶ ЗАПУСТИТЬ ДИАГНОСТИКУ",
                    on_click=lambda: asyncio.create_task(run_diag())
                ).props("no-caps").style(
                    "background:rgba(59,130,246,.15);border:1px solid var(--accent);"
                    "color:var(--accent);font-family:var(--font);font-weight:900;font-size:.75rem;"
                )
                ui.button(
                    "📋 В ЛОГ",
                    on_click=lambda: _diag_to_log()
                ).props("no-caps flat").style("font-size:.7rem;color:var(--dim);")

        # ── Итоговые KPI диагностики ─────────────
        with ui.row().classes("w-full gap-3"):
            diag_overall = _html(
                '<div class="kpi-box flex-1" style="text-align:center;">'
                '<div class="kpi-val" style="font-size:2rem;">—</div>'
                '<div class="kpi-lbl">ОБЩИЙ СТАТУС</div></div>'
            )
            diag_ok_kpi   = _diag_kpi_box("—", "ОК",          "var(--ok)")
            diag_warn_kpi = _diag_kpi_box("—", "ПРЕДУПРЕЖДЕНИЙ", "var(--warn)")
            diag_err_kpi  = _diag_kpi_box("—", "ОШИБОК",      "var(--err)")
            diag_time_kpi = _diag_kpi_box("—", "ВРЕМЯ (мс)",  "var(--dim)")

        # ── Визуализация — карточки чеков ────────
        diag_cards = ui.grid(columns=2).classes("w-full gap-3")

        # ── Mermaid-схема состояния ───────────────
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between mb-2"):
                _html('<div class="section-title">ТОПОЛОГИЯ // СТАТУС УЗЛОВ</div>')
                ui.label("Обновляется после диагностики").style("font-size:.6rem;color:var(--dim);")
            diag_mermaid = ui.mermaid(
                "graph LR\n"
                "  UI([С.О.В.У.Ш.К.А.\n:8051]) --> P[les-proxy\n:8050]\n"
                "  P --> Q[(Qdrant\n:6333)]\n"
                "  P --> M[MLX Host\n:8080]\n"
                "  P --> O[Ollama\n:11434]\n"
                "  M --> B[bge-m3\nEmbeddings]\n"
                "  M --> L[Qwen3-14B\nLLM]\n"
                "  M --> V[Qwen3-4B\nValidator]"
            ).classes("w-full")

        # ── Лог диагностики ───────────────────────
        with ui.card().classes("card-les w-full"):
            _html('<div class="section-title" style="margin-bottom:8px;">ЛОГ ПРОГОНА</div>')
            diag_log_el = ui.log(max_lines=80).classes("w-full").style(
                "background:var(--bg);color:var(--ok);font-family:var(--font);"
                "font-size:.68rem;height:160px;border:none;"
            )

    # ── Вспомогательные функции диагностики ──────────

    STATUS_ICON  = {"ok": "✓", "warn": "⚠", "err": "✗"}
    STATUS_COLOR = {"ok": "var(--ok)", "warn": "var(--warn)", "err": "var(--err)"}
    STATUS_TAG   = {"ok": "tag-ok", "warn": "tag-warn", "err": "tag-err"}

    def _render_diag_cards():
        results = state["diag_results"]
        diag_cards.clear()
        with diag_cards:
            for r in results:
                s = r["status"]
                color = STATUS_COLOR.get(s, "var(--dim)")
                icon  = STATUS_ICON.get(s, "?")
                tag   = STATUS_TAG.get(s, "tag-dim")
                with ui.card().classes("card-les").style(
                    f"border-left:3px solid {color};"
                ):
                    with ui.row().classes("items-center justify-between mb-1"):
                        ui.label(r["name"]).style(
                            "font-size:.78rem;font-weight:900;color:var(--text);"
                        )
                        _html(f'<span class="{tag}">{icon} {s.upper()}</span>')
                    with ui.row().classes("items-center gap-3"):
                        ui.label(r["value"]).style(
                            f"font-size:.85rem;font-weight:900;color:{color};"
                        )
                        ui.label(f"ожидалось: {r['expected']}").style(
                            "font-size:.6rem;color:var(--dim);"
                        )
                    if r.get("message"):
                        ui.label(r["message"]).style(
                            "font-size:.65rem;color:var(--dim);margin-top:2px;"
                        )
                    ui.label(f"⏱ {r['latency_ms']} ms").style(
                        "font-size:.6rem;color:var(--border-hl, #4a5568);margin-top:4px;"
                    )

    def _build_diag_mermaid(results: list) -> str:
        """Строит Mermaid-диаграмму с цветами по статусу каждого узла."""
        node_map = {
            "Qdrant :6333":          ("QD", "Qdrant\n:6333"),
            "Qdrant индекс":         ("QI", "Qdrant\nindex"),
            "MLX Host :8080":        ("ML", "MLX Host\n:8080"),
            "Ollama :11434":         ("OL", "Ollama\n:11434"),
            "RAM":                   ("RAM", "RAM"),
            "CPU":                   ("CPU", "CPU"),
            "Диск":                  ("DSK", "Диск"),
            "Docker":                ("DK", "Docker"),
            "Chat latency (тест)":   ("CH", "Chat\nlatency"),
            "Сеть (интернет)":       ("NET", "Интернет"),
        }
        status_style = {"ok": "fill:#10b981,color:#fff", "warn": "fill:#f59e0b,color:#000", "err": "fill:#ef4444,color:#fff"}

        result_map = {r["name"]: r["status"] for r in results}

        lines = ["graph LR"]
        styles = []

        lines.append('  UI([С.О.В.У.Ш.К.А.\n:8051])')
        lines.append('  P[les-proxy\n:8050]')
        lines.append('  UI --> P')

        for name, (nid, label) in node_map.items():
            st = result_map.get(name, "idle")
            shape_open, shape_close = "[", "]"
            if nid in ("QD", "QI"):
                shape_open, shape_close = "[(", ")]"
            elif nid in ("RAM", "CPU", "DSK"):
                shape_open, shape_close = "{{", "}}"
            elif nid == "NET":
                shape_open, shape_close = "([", "])"
            lines.append(f'  {nid}{shape_open}"{label}"{shape_close}')
            if st in status_style:
                styles.append(f'  style {nid} {status_style[st]}')

        lines += [
            "  P --> QD", "  QD --> QI",
            "  P --> ML", "  ML --> OL",
            "  P --> CH",
            "  P --> RAM", "  P --> CPU", "  P --> DSK",
            "  UI --> NET",
            "  DK --> P", "  DK --> QD",
        ]
        lines += styles
        return "\n".join(lines)

    async def run_diag():
        if state["diag_running"]:
            ui.notify("Диагностика уже запущена", type="warning")
            return

        state["diag_running"] = True
        diag_run_btn.props("disabled")
        diag_run_btn.set_text("⌛ Диагностика...")
        diag_log_el.clear()

        add_log("[DIAG] ▶ Запуск диагностики системы...")
        diag_log_el.push("> [С.О.В.У.Ш.К.А.] Запуск диагностики...")

        try:
            d = await api_get("/api/diag")

            if d is None:
                diag_log_el.push("> [WARN] /api/diag не найден — запуск встроенной диагностики")
                d = await _run_local_diag()

            state["diag_results"] = d.get("checks", [])
            overall = d.get("overall", "warn")
            ok_c    = d.get("ok_count", 0)
            warn_c  = d.get("warn_count", 0)
            err_c   = d.get("err_count", 0)
            total_ms = d.get("total_ms", 0)
            ts      = d.get("timestamp", "—")

            overall_icon = {"ok": "✓ ОК", "warn": "⚠ WARN", "err": "✗ ОШИБКИ"}.get(overall, "?")
            overall_color = STATUS_COLOR.get(overall, "var(--dim)")
            diag_overall.set_content(
                f'<div class="kpi-box flex-1" style="text-align:center;border-color:{overall_color};">'
                f'<div class="kpi-val" style="font-size:2rem;color:{overall_color};">{overall_icon}</div>'
                f'<div class="kpi-lbl">ОБЩИЙ СТАТУС</div></div>'
            )
            diag_ok_kpi.set_text(str(ok_c))
            diag_warn_kpi.set_text(str(warn_c))
            diag_err_kpi.set_text(str(err_c))
            diag_time_kpi.set_text(f"{total_ms:.0f}")
            diag_ts_lbl.set_text(f"Последний прогон: {ts}")

            _render_diag_cards()

            mermaid_code = _build_diag_mermaid(state["diag_results"])
            diag_mermaid.set_content(mermaid_code)

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
            diag_run_btn.set_text("▶ ЗАПУСТИТЬ ДИАГНОСТИКУ")

    async def _run_local_diag() -> dict:
        """Встроенная диагностика — имена чеков соответствуют node_map в _build_diag_mermaid."""
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

        # ── MLX Host — имя совпадает с node_map ──
        async def chk_mlx():
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
        await _chk("MLX Host :8080", chk_mlx())

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

        # ── Ollama ──
        async def chk_ollama():
            r = await api_get("/api/status")
            if not r:
                return "warn", "—", "UP", "status недоступен"
            ol = r.get("ollama", {})
            models = ol.get("models", [])
            if models:
                return "ok", f"{len(models)} models", "≥1", ""
            return "warn", "0 models", "≥1", "Нет загруженных моделей"
        await _chk("Ollama :11434", chk_ollama())

        # ── Docker ──
        async def chk_docker():
            r = await api_get("/api/status")
            if not r:
                return "warn", "—", "UP", "status недоступен"
            containers = r.get("containers", [])
            if not containers:
                return "warn", "0 containers", "≥1", ""
            all_ok = all(c.get("ok") for c in containers)
            return ("ok" if all_ok else "err"), f"{len(containers)} containers", "all UP", ""
        await _chk("Docker", chk_docker())

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

    def _diag_to_log():
        results = state.get("diag_results", [])
        if not results:
            add_log("[DIAG] Нет данных — сначала запусти диагностику")
            ui.notify("Сначала запусти диагностику", type="warning")
            return
        add_log("─" * 60)
        add_log("[DIAG] ОТЧЁТ ДИАГНОСТИКИ СИСТЕМЫ Л.Е.С.")
        add_log("─" * 60)
        for r in results:
            icon = STATUS_ICON.get(r["status"], "?")
            add_log(f"[DIAG] {icon} {r['name']}: {r['value']}  ({r['latency_ms']}ms)"
                    + (f" — {r['message']}" if r.get("message") else ""))
        add_log("─" * 60)
        ui.notify("Результаты записаны в лог", type="positive")


def _diag_kpi_box(val: str, lbl: str, color: str):
    """Хелпер для отрисовки KPI."""
    with ui.card().classes("kpi-box flex-1"):
        v = ui.label(val).style(f"font-size:1.6rem;font-weight:900;color:{color};")
        ui.label(lbl).style("font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;")
    return v
