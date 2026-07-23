from proxy.services.active_state_service import ActiveState, ActiveStateStore, render_active_state


def test_active_state_is_module_scoped():
    store = ActiveStateStore()
    store.set("s1", ActiveState(module_id="smeta", task="Оценка СКС", status="scenario"))
    store.set("s2", ActiveState(module_id="normcontrol", task="Проверка ПД", status="draft"))

    assert store.get("s1").module_id == "smeta"
    assert store.get("s2").module_id == "normcontrol"


def test_active_state_render_marks_working_memory_not_proof():
    state = ActiveState(
        module_id="smeta",
        task="Оценка столпа",
        current_result="ВОР собрана",
        open_branches=["вариант А", "вариант Б"],
        current_objects=[{"title": "Монтаж", "status": "draft"}],
    )
    text = render_active_state(state)
    assert "рабочую память" in text
    assert "проверяй по источникам" in text
    assert "Открытые развилки: вариант А; вариант Б" in text
    assert "Монтаж" in text


def test_active_state_patch_continues_existing_task():
    store = ActiveStateStore()
    store.set("chat", ActiveState(module_id="smeta", task="Оценка СКС", current_result="ВОР"))
    patched = store.patch("chat", last_action="добавлены номера ГЭСН")
    assert patched.task == "Оценка СКС"
    assert patched.last_action == "добавлены номера ГЭСН"
