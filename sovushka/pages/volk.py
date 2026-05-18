"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка В.О.Л.К. (RBAC / ключи)
"""
from __future__ import annotations

import asyncio
from nicegui import app, ui

from sovushka.state import api_get, api_post, api_delete


def build_volk():
    """Строит содержимое вкладки В.О.Л.К. Вызывать внутри with ui.tab_panel(tab_volk)."""
    raw_key = app.storage.user.get("key", "")

    with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label("В.О.Л.К. // УПРАВЛЕНИЕ ДОСТУПОМ").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label("Ключи хранятся в les_meta.db · cookie: les_key · 30 дней").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            ui.button(
                "↻ ОБНОВИТЬ",
                on_click=lambda: asyncio.create_task(_volk_load())
            ).props("no-caps outline").style(
                "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
            )

        # ── Форма создания ключа ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("НОВЫЙ КЛЮЧ").classes("section-title mb-3")
            with ui.row().classes("w-full gap-2 items-end"):
                inp_key = ui.input("Ключ").classes("flex-1").style(
                    "background:var(--bg);border:1px solid var(--border);"
                    "color:var(--text);font-family:var(--font);"
                    "border-radius:4px;padding:6px 10px;font-size:.75rem;"
                )
                inp_holder = ui.input("Имя").style(
                    "background:var(--bg);border:1px solid var(--border);"
                    "color:var(--text);font-family:var(--font);"
                    "border-radius:4px;padding:6px 10px;font-size:.75rem;width:160px;"
                )
                inp_role = ui.select(["user", "admin"], value="user", label="Роль").style(
                    "font-size:.72rem;width:100px;"
                )
                inp_type = ui.select(
                    {"permanent": "∞ Постоянный", "1": "⏱ 1 день"},
                    value="permanent", label="Срок"
                ).style("font-size:.72rem;width:130px;")

            with ui.row().classes("gap-2 mt-2"):
                def _gen():
                    import secrets
                    inp_key.set_value("les_" + secrets.token_hex(8))

                ui.button("🎲 Сгенерировать", on_click=_gen).props("no-caps flat").style(
                    "font-size:.7rem;color:var(--dim);"
                )
                ui.button(
                    "✚ СОЗДАТЬ",
                    on_click=lambda: asyncio.create_task(_volk_create())
                ).props("no-caps").style(
                    "border:1px solid var(--ok);color:var(--ok);"
                    "background:transparent;font-size:.7rem;"
                )

        # ── Таблица ключей ──────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("КЛЮЧИ ДОСТУПА").classes("section-title mb-3")
            volk_cols = [
                {"name": "holder_name",  "label": "Кто",       "field": "holder_name",  "align": "left",   "sortable": True},
                {"name": "role",         "label": "Роль",      "field": "role",         "align": "center"},
                {"name": "key_value",    "label": "Ключ",      "field": "key_value",    "align": "left"},
                {"name": "is_active",    "label": "Статус",    "field": "is_active",    "align": "center"},
                {"name": "device_bound", "label": "Устройство","field": "device_bound", "align": "center"},
                {"name": "expires_at",   "label": "Истекает",  "field": "expires_at",   "align": "left"},
                {"name": "created_at",   "label": "Создан",    "field": "created_at",   "align": "left",   "sortable": True},
                {"name": "actions",      "label": "",           "field": "key_value",    "align": "center"},
            ]
            volk_tbl = ui.table(columns=volk_cols, rows=[], row_key="key_value").classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            )
            volk_tbl.add_slot("body-cell-is_active", """
                <q-td :props="props">
                  <span :style="{color:props.value?'#10b981':'#ef4444',fontWeight:'700'}">
                    {{ props.value ? 'ON' : 'OFF' }}
                  </span>
                </q-td>""")
            volk_tbl.add_slot("body-cell-expires_at", """
                <q-td :props="props">
                  <span :style="{color:props.value?'#f59e0b':'#94a3b8',fontSize:'.65rem'}">
                    {{ props.value ? props.value.substring(0,10) : '∞' }}
                  </span>
                </q-td>""")
            volk_tbl.add_slot("body-cell-role", """
                <q-td :props="props">
                  <span :style="{color:props.value==='admin'?'#8b5cf6':'#94a3b8',fontWeight:'700',fontSize:'.65rem'}">
                    {{ props.value.toUpperCase() }}
                  </span>
                </q-td>""")
            volk_tbl.add_slot("body-cell-device_bound", """
                <q-td :props="props" auto-width>
                  <span :style="{color:props.value?'#f59e0b':'#94a3b8',fontSize:'.65rem',fontWeight:'700'}">
                    {{ props.value ? '📱 привязан' : '🔓 свободен' }}
                  </span>
                </q-td>""")
            volk_tbl.add_slot("body-cell-actions", """
                <q-td :props="props" auto-width>
                  <q-btn flat dense size="xs" color="warning"
                         @click="$parent.$emit('toggle', props.row)"
                         style="font-size:.6rem;margin-right:4px;">
                    {{ props.row.is_active ? 'OFF' : 'ON' }}
                  </q-btn>
                  <q-btn v-if="props.row.device_bound" flat dense size="xs" color="info"
                         @click="$parent.$emit('reset_device', props.row)"
                         style="font-size:.6rem;margin-right:4px;">📱✕</q-btn>
                  <q-btn flat dense size="xs" color="negative"
                         @click="$parent.$emit('delete', props.row)"
                         style="font-size:.6rem;">DEL</q-btn>
                </q-td>""")
            volk_tbl.on("toggle", lambda e: asyncio.create_task(_volk_toggle(e.args)))
            volk_tbl.on("reset_device", lambda e: asyncio.create_task(_volk_reset_device(e.args)))
            volk_tbl.on("delete", lambda e: asyncio.create_task(_volk_delete(e.args)))

        # ── Логика ──────────────────────────────

        async def _volk_load():
            rows = await api_get("/api/auth/keys")
            if rows is not None:
                volk_tbl.rows = rows
                volk_tbl.update()

        async def _volk_create():
            k  = inp_key.value.strip()
            h  = inp_holder.value.strip()
            ro = inp_role.value
            tp = inp_type.value
            if not k:
                ui.notify("Введите или сгенерируйте ключ", type="warning")
                return
            expires_days = 0 if tp == "permanent" else int(tp)
            d = await api_post("/api/auth/keys", {
                "key_value": k, "holder_name": h,
                "role": ro, "expires_days": expires_days
            })
            if d:
                kind = "∞ постоянный" if expires_days == 0 else f"⏱ {expires_days}д"
                ui.notify(f"✓ Создан: {h or k} [{ro}] {kind}", type="positive")
                inp_key.set_value("")
                inp_holder.set_value("")
                await _volk_load()
            else:
                ui.notify("Ошибка (ключ уже существует?)", type="negative")

        async def _volk_toggle(row):
            k   = row.get("key_value", "") if isinstance(row, dict) else str(row)
            cur = row.get("is_active", 1)  if isinstance(row, dict) else 1
            await api_post("/api/auth/keys/toggle", {"key_value": k, "is_active": 0 if cur else 1})
            await _volk_load()

        async def _volk_reset_device(row):
            k = row.get("key_value", "") if isinstance(row, dict) else str(row)
            h = row.get("holder_name", k) if isinstance(row, dict) else k
            await api_post("/api/auth/keys/reset-device", {"key_value": k, "is_active": 1})
            ui.notify(f"📱 Устройство отвязано: {h}", type="info")
            await _volk_load()

        async def _volk_delete(row):
            k = row.get("key_value", "") if isinstance(row, dict) else str(row)
            if k == raw_key:
                ui.notify("Нельзя удалить свой ключ", type="warning")
                return
            await api_delete(f"/api/auth/keys/{k}")
            ui.notify(f"Удалён: {k[:16]}…", type="warning")
            await _volk_load()

        ui.timer(0.5, lambda: asyncio.create_task(_volk_load()), once=True)
