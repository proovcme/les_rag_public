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


def test_model_rag_failure_keeps_query_indices_and_safe_reasons():
    payload = public_error_payload(status_code=503, detail={
        "error": "MODEL_RAG_SEARCH_INCOMPLETE",
        "blocked_queries": [2, 4],
        "query_failures": [
            {"query_index": 2, "status": "missing", "operation": "smeta_norm_native_rrf",
             "collection": "les_smeta_norm_cards", "error_code": "", "reason": "no_matches"},
            {"query_index": 4, "status": "blocked", "operation": "native_rrf",
             "collection": "les_rag", "error_code": "RAG_NOT_READY",
             "reason": "generation_coverage_incomplete", "raw_exception": "password=secret"},
        ],
        "trace": {"authorization": "secret"},
    })
    assert payload['code'] == 'MODEL_RAG_SEARCH_INCOMPLETE'
    assert payload['blocked_queries'] == [2, 4]
    assert payload['query_failures'][0]['status'] == 'missing'
    assert payload['query_failures'][1]['reason'] == 'generation_coverage_incomplete'
    assert '2' in payload['detail'] and '4' in payload['detail']
    assert 'secret' not in str(payload) and 'raw_exception' not in str(payload)


def test_unknown_server_error_dict_is_still_hidden():
    payload = public_error_payload(status_code=503, detail={
        'error': 'password=secret', 'blocked_queries': [1], 'trace': 'private',
    })
    assert payload['code'] == 'MODEL_SERVICE_UNAVAILABLE'
    assert 'secret' not in str(payload) and 'private' not in str(payload)
