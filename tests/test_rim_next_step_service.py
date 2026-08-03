from proxy.services.rim_next_step_service import next_step_for_session


def test_saved_mapping_has_explicit_continue_action():
    step = next_step_for_session(
        {
            "phase": "mapping",
            "mapping_status": "mapping_selected",
            "scenario_status": "not_started",
            "pricing_status": "unpriced",
            "pending_question_id": "",
        }
    )

    assert step["kind"] == "agent_turn"
    assert step["label"] == "Продолжить проверку и расчёт"
    assert "без повторного поиска всех строк" in step["detail"]


def test_dialog_ready_means_final_only_for_priced_final():
    draft = next_step_for_session(
        {
            "phase": "pricing",
            "mapping_status": "mapping_globally_reviewed",
            "scenario_status": "ready",
            "pricing_status": "priced_draft",
            "pending_question_id": "",
        }
    )
    final = next_step_for_session(
        {
            "phase": "final",
            "mapping_status": "mapping_locked",
            "scenario_status": "ready",
            "pricing_status": "priced_final",
            "pending_question_id": "",
        }
    )

    assert draft["kind"] == "review_draft"
    assert final["kind"] == "complete"
