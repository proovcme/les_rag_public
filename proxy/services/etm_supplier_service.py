"""Read-only client for the official ETM buyer API, with exact quote identity.

Contract: https://ipro.etm.ru/ns2000/yaml/cli.yaml and components.yaml.
No orders, professional matching, hidden activation or automatic price adoption.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
import logging
import math
import os
import re
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import quote

import httpx

BASE_URL = 'https://ipro.etm.ru/api/v1'
ALLOWED_BASE_URLS = {BASE_URL, 'https://itest.etm.ru/api/v1'}
SESSION_TTL = 2 * 60 * 60 - 60
MAX_CODES = 50
_CODE = re.compile(r'^(?:ETM)?([0-9]{1,20})$', re.I)
_CREDENTIAL_QUERY = re.compile(r'([?&](?:log|pwd|session-id)=)[^&\s\'"<>]+', re.I)


class EtmError(ValueError):
    """Only a stable code crosses the application boundary; no provider URL/body."""


class _CredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _CREDENTIAL_QUERY.sub(r'\1***', message)
        if message != redacted:
            record.msg, record.args = redacted, ()
        return True


_LOG_FILTER = _CredentialFilter()


def error_message(code: str) -> str:
    return {
        'disabled': 'ЭТМ выключен. Включите «Использовать цены ЭТМ» в параметрах выполнения.',
        'needs_credentials': 'Задайте логин и пароль iPRO в защищённых полях параметров выполнения.',
        'invalid_endpoint': 'Укажите официальный рабочий или тестовый адрес клиентского API ЭТМ.',
        'invalid_timeout': 'Ожидание API ЭТМ должно быть от 1 до 60 секунд.',
        'authentication_failed': 'ЭТМ не подтвердил авторизацию. Проверьте учётную запись и доступ к API.',
        'access_or_lookup_failed': 'ЭТМ не разрешил чтение. Проверьте доступ учётной записи к API.',
        'invalid_product_code': 'Нужны числовые коды товаров ЭТМ. Артикул производителя сначала найдите в каталоге.',
        'timeout': 'API ЭТМ не ответил вовремя. Попробуйте позже.',
        'network_or_response_error': 'Не удалось получить ответ API ЭТМ. Проверьте соединение.',
        'price_not_found': 'Цена не найдена.',
        'conflicting_price_rows': 'ЭТМ вернул противоречивые строки цены по одному коду.',
        'individual_quote_required': 'Нужна индивидуальная цена или коммерческое предложение ЭТМ.',
        'product_identity_or_unit_unconfirmed': 'Карточка товара или единица цены не подтверждены.',
    }.get(code, 'Ответ ЭТМ не удалось подтвердить. Проверьте доступ и повторите запрос.')


@dataclass(frozen=True)
class EtmConfig:
    login: str = field(repr=False)
    password: str = field(repr=False)
    base_url: str = BASE_URL
    timeout: float = 20

    def __post_init__(self):
        if self.base_url.rstrip('/') not in ALLOWED_BASE_URLS:
            raise EtmError('invalid_endpoint')
        if not self.login.strip() or not self.password or any(c in self.login + self.password for c in '\r\n\0'):
            raise EtmError('needs_credentials')
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 60:
            raise EtmError('invalid_timeout')


def configuration_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    enabled = values.get('LES_ETM_ENABLED', '0').lower() in {'1', 'true'}
    configured = bool(values.get('LES_ETM_LOGIN', '').strip() and values.get('LES_ETM_PASSWORD', ''))
    return {'schema': 'etm_supplier_status_v1', 'enabled': enabled, 'configured': configured,
            'state': 'disabled' if not enabled else ('not_checked' if configured else 'needs_credentials'),
            'read_only': True, 'base_url': (values.get('LES_ETM_BASE_URL', BASE_URL)
                                          if values.get('LES_ETM_BASE_URL', BASE_URL).rstrip('/') in ALLOWED_BASE_URLS else None),
            'session_ttl_sec': SESSION_TTL,
            'max_codes_per_request': MAX_CODES, 'price_interval_sec': 1,
            'historical_prices': False, 'independent_suppliers': 1}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _code(value: Any) -> str:
    match = _CODE.fullmatch(str(value).strip())
    if not match:
        raise EtmError('invalid_product_code')
    return match[1]


class EtmClient:
    def __init__(self, config: EtmConfig, *, http: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.http = http or httpx.Client(timeout=config.timeout, follow_redirects=False)
        self._owns_http = http is None
        self.clock, self.sleep = clock, sleep
        self._lock = threading.RLock()
        self._session = ''
        self._expires = 0.0
        self._last_price: float | None = None
        self._last_success: float | None = None
        # Official login uses query credentials. Redact these at HTTP log boundaries.
        for name in ('httpx', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
            logger = logging.getLogger(name)
            if _LOG_FILTER not in logger.filters:
                logger.addFilter(_LOG_FILTER)

    def close(self):
        with self._lock:
            if self._owns_http:
                self.http.close()

    def _request(self, method: str, path: str, *, params=None, headers=None) -> tuple[int, dict[str, Any]]:
        self._last_success = None
        try:
            response = self.http.request(method, self.config.base_url.rstrip('/') + path,
                                         params=params, headers=headers, follow_redirects=False)
            if response.status_code not in {200, 403}:
                raise EtmError('http_error')
            payload = response.json()
        except httpx.TimeoutException:
            self._last_success = None
            raise EtmError('timeout') from None
        except (httpx.HTTPError, ValueError) as error:
            self._last_success = None
            if isinstance(error, EtmError):
                raise
            raise EtmError('network_or_response_error') from None
        if not isinstance(payload, dict):
            raise EtmError('invalid_response')
        try:
            code = int((payload.get('status') or {}).get('code', response.status_code))
        except (TypeError, ValueError, AttributeError):
            raise EtmError('invalid_response') from None
        return (403 if response.status_code == 403 else code), payload

    def _login(self):
        code, payload = self._request('POST', '/user/login',
                                      params={'log': self.config.login, 'pwd': self.config.password})
        data = payload.get('data')
        session = data.get('session') if isinstance(data, dict) else None
        if code != 200 or not isinstance(session, str) or not session:
            raise EtmError('authentication_failed')
        self._session, self._expires = session, self.clock() + SESSION_TTL

    def _get(self, path: str, params=None, *, price=False) -> list[dict[str, Any]]:
        with self._lock:
            for attempt in range(2):
                if not self._session or self.clock() >= self._expires:
                    self._login()
                if price:
                    if self._last_price is not None:
                        self.sleep(max(0, 1 - (self.clock() - self._last_price)))
                    self._last_price = self.clock()
                code, payload = self._request('GET', path, params=params,
                                              headers={'session-id': self._session})
                if code == 403 and attempt == 0:
                    self._session, self._expires = '', 0
                    continue
                if code != 200:
                    self._last_success = None
                    raise EtmError('access_or_lookup_failed')
                data = payload.get('data')
                rows = data.get('rows') if isinstance(data, dict) else None
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    self._last_success = None
                    raise EtmError('invalid_response')
                self._last_success = self.clock()
                return rows
        raise EtmError('access_or_lookup_failed')

    def search(self, query: str, *, page=1, rows=20, exact_code=False) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise EtmError('invalid_query')
        if isinstance(page, bool) or isinstance(rows, bool) or not 1 <= page <= 10000 or not 1 <= rows <= 50:
            raise EtmError('invalid_page')
        params = {'val': query, 'page': page, 'rows': rows}
        if exact_code:
            params['type'] = 'code'
        raw = self._get('/catalog', params)
        result = []
        for record in raw:
            try:
                code = _code(record.get('gdscode', record.get('code', '')))
            except EtmError:
                continue
            result.append({'code': code, 'name': str(record.get('name') or ''),
                           'article': str(record.get('art') or ''), 'unit': str(record.get('edizm') or ''),
                           'manufacturer': str(record.get('mnf_name') or ''), 'pack': str(record.get('pack') or '')})
        return {'schema': 'etm_catalog_v1', 'query': query, 'page': page, 'rows': result,
                'source': self.config.base_url.rstrip('/') + '/catalog',
                'retrieved_at': datetime.now(timezone.utc).isoformat()}

    def probe(self):
        self._get('/catalog', {'page': 1, 'rows': 1})
        return {'ok': True, 'state': 'connected', 'read_only': True}

    def connected(self) -> bool:
        return self._last_success is not None and bool(self._session) and self.clock() < self._expires

    def quotes(self, codes: list[str]) -> dict[str, Any]:
        with self._lock:
            return self._quotes(codes)

    def _quotes(self, codes: list[str]) -> dict[str, Any]:
        if not 1 <= len(codes) <= 500:
            raise EtmError('invalid_code_count')
        normalized = list(dict.fromkeys(_code(code) for code in codes))
        by_code: dict[str, list[dict[str, Any]]] = {}
        for start in range(0, len(normalized), MAX_CODES):
            batch = normalized[start:start + MAX_CODES]
            raw = self._get('/goods/' + quote(','.join(batch), safe=',') + '/price', {'type': 'etm'}, price=True)
            for record in raw:
                try:
                    code = _code(record.get('gdscode', ''))
                except EtmError:
                    continue
                if code in batch:
                    by_code.setdefault(code, []).append(record)
        date = datetime.now(timezone.utc).isoformat()
        rows, quotes = [], []
        for code in normalized:
            records = by_code.get(code, [])
            price = _number(records[0].get('price')) if len(records) == 1 else None
            reason = ('conflicting_price_rows' if len(records) > 1 else
                      'price_not_found' if not records else 'individual_quote_required' if not price else '')
            cards = [] if reason else [r for r in self.search(code, exact_code=True)['rows'] if r['code'] == code]
            if not reason and (len(cards) != 1 or not cards[0]['name'] or not cards[0]['unit']):
                reason = 'product_identity_or_unit_unconfirmed'
            item = {'code': code, 'found': not reason, 'reason': reason}
            rows.append(item)
            if reason:
                continue
            card = cards[0]
            quote_row = {'material': card['name'], 'supplier': 'ЭТМ', 'unit': card['unit'],
                         'price': price, 'price_gross': _number(records[0].get('pricewnds')),
                         'price_includes_vat': False, 'vat_pct': None,
                         'vat_basis': 'ETM buyer API: price is explicitly net of VAT',
                         'source': self.config.base_url.rstrip('/') + '/goods/' + code + '/price?type=etm',
                         'source_kind': 'supplier_api', 'product_code': code, 'article': card['article'],
                         'retrieved_at': date, 'period_basis': 'current_supplier_quote'}
            quotes.append(quote_row)
            item.update(quote_row)
        return {'schema': 'etm_supplier_quotes_v1', 'supplier': 'ЭТМ', 'requested': len(normalized),
                'found': len(quotes), 'missing': len(normalized) - len(quotes), 'rows': rows, 'quotes': quotes,
                'retrieved_at': date, 'historical_prices': False, 'independent_suppliers': 1}


_SHARED_LOCK = threading.RLock()
_SHARED_CLIENT: EtmClient | None = None


def _configured_client_config() -> EtmConfig:
    status = configuration_status()
    if not status['enabled']:
        raise EtmError('disabled')
    if not status['configured']:
        raise EtmError('needs_credentials')
    try:
        timeout = float(os.getenv('LES_ETM_TIMEOUT_SEC', '20'))
    except ValueError:
        raise EtmError('invalid_timeout') from None
    return EtmConfig(os.getenv('LES_ETM_LOGIN', ''), os.getenv('LES_ETM_PASSWORD', ''),
                     os.getenv('LES_ETM_BASE_URL', BASE_URL), timeout)


def get_client() -> EtmClient:
    global _SHARED_CLIENT
    config = _configured_client_config()
    with _SHARED_LOCK:
        if _SHARED_CLIENT is None or _SHARED_CLIENT.config != config:
            if _SHARED_CLIENT is not None:
                _SHARED_CLIENT.close()
            _SHARED_CLIENT = EtmClient(config)
        return _SHARED_CLIENT


def source_status() -> dict[str, Any]:
    status = configuration_status()
    with _SHARED_LOCK:
        if status['enabled'] and status['configured']:
            try:
                config = _configured_client_config()
            except EtmError:
                status['state'] = 'invalid_configuration'
            else:
                if (_SHARED_CLIENT is not None and _SHARED_CLIENT.config == config
                        and _SHARED_CLIENT.connected()):
                    status['state'] = 'connected'
    return status


def quotes_to_xlsx(result: Mapping[str, Any]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = 'Прайс ЭТМ'
    sheet.append(['Код ЭТМ', 'Наименование', 'Ед. изм.', 'Цена без НДС', 'Цена с НДС',
                  'Артикул', 'Поставщик', 'Источник цены', 'Дата получения', 'Причина пропуска'])
    for row in result.get('rows', []):
        sheet.append([row['code'], row.get('material'), row.get('unit'), row.get('price'), row.get('price_gross'),
                      row.get('article'), 'ЭТМ', row.get('source'), row.get('retrieved_at'),
                      error_message(row['reason']) if row.get('reason') else ''])
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    # All text returned by the supplier stays literal, including formula-like names.
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
