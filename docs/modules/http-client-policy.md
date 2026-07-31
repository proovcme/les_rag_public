# HTTP client policy — loopback без системного proxy

## Назначение

`backend/http_client_policy.py` задаёт одну узкую сетевую границу: вызовы
`localhost`, `*.localhost`, `127.0.0.0/8` и `::1` не наследуют
`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`. Это защищает внутренние связи
С.О.В.У.Ш.К.А. → proxy, proxy → MLX/Qdrant и локальную диагностику от
невалидной или корпоративной SOCKS-конфигурации.

Внешние URL и адреса LAN/ZeroTier не объявляются loopback и сохраняют обычное
поведение `httpx` (`trust_env=True`). Политика не чистит окружение процесса,
не меняет DNS и не отключает proxy для ETM, облачных дисков, обновлений и
других интернет-сервисов.

## Точки входа

- `is_loopback_url(url)` — строгая классификация URL;
- `trust_env_for_url(url)` — значение для `httpx.Client/AsyncClient`;
- критические вызовы: `sovushka/state.py`, `sovushka/lite_bridge.py`,
  `proxy/app.py`, `proxy/routers/{diagnostics,runtime}.py`,
  `backend/{metrics_collector,reranker}.py`.

## Проверка

`tests/test_http_client_policy.py` проверяет IPv4/IPv6/localhost, сохраняет
proxy-policy для внешних и private-network URL, воспроизводит невалидный
`ALL_PROXY=socks4://…` и статически удерживает критические call sites на общем
helper.
