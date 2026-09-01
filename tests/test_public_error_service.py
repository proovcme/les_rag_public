from proxy.services.public_error_service import public_error_payload


def test_internal_error_payload_hides_exception_details():
    payload = public_error_payload(
        status_code=500,
        detail="ValueError: password=do-not-leak",
    )

    assert payload == {
        "code": "INTERNAL_CHAT_ERROR",
        "detail": "Не удалось завершить запрос. Повторите попытку или откройте диагностику.",
    }
    assert "password" not in str(payload)
    assert "ValueError" not in str(payload)


def test_model_queue_timeout_keeps_stable_code_and_message():
    payload = public_error_payload(
        status_code=429,
        detail={
            "code": "MODEL_QUEUE_TIMEOUT",
            "detail": "Модель занята. Запрос дождался своей очереди, но время ожидания истекло.",
        },
    )

    assert payload["code"] == "MODEL_QUEUE_TIMEOUT"
    assert "очеред" in payload["detail"]


def test_known_user_rejection_remains_readable():
    payload = public_error_payload(status_code=409, detail="Запрос уже выполняется")

    assert payload == {"code": "REQUEST_REJECTED", "detail": "Запрос уже выполняется"}
