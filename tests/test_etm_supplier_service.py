import logging

import httpx
import pytest

from proxy.services.etm_supplier_service import EtmClient, EtmConfig, EtmError, configuration_status


def client(handler, clock=lambda: 0):
    return EtmClient(EtmConfig('test-login', 'test-password'),
                     http=httpx.Client(transport=httpx.MockTransport(handler)), clock=clock,
                     sleep=lambda _: None)


def login():
    return httpx.Response(200, json={'status': {'code': 200}, 'data': {'session': 'test-session'}})


def test_configuration_status_neither_exposes_credentials_nor_claims_connection():
    status = configuration_status({'LES_ETM_ENABLED': '1', 'LES_ETM_LOGIN': 'test-login',
                                   'LES_ETM_PASSWORD': 'test-password'})
    assert status['configured'] is True and status['state'] == 'not_checked'
    assert 'test-login' not in str(status) and 'test-password' not in str(status)


def test_session_expires_before_official_two_hour_limit():
    calls, now = [], [0]
    def handler(request):
        calls.append(request)
        return login() if request.url.path.endswith('/user/login') else httpx.Response(
            200, json={'status': {'code': 200}, 'data': {'rows': []}})
    api = client(handler, clock=lambda: now[0])
    api.search('cable')
    now[0] = 7100
    api.search('cable')
    now[0] = 7200
    api.search('cable')
    assert sum(r.url.path.endswith('/user/login') for r in calls) == 2
    assert all(r.headers.get('session-id') == 'test-session' for r in calls if r.method == 'GET')


def test_wrong_or_duplicate_returned_codes_cannot_be_assigned_by_row_order():
    def handler(request):
        if request.url.path.endswith('/user/login'):
            return login()
        if request.url.path.endswith('/catalog'):
            return httpx.Response(200, json={'status': {'code': 200}, 'data': {'rows': [
                {'gdscode': 1, 'name': 'Cable', 'edizm': 'м'},
                {'gdscode': 2, 'name': 'Cabinet', 'edizm': 'шт'}]}})
        return httpx.Response(200, json={'status': {'code': 200}, 'data': {'rows': [
            {'gdscode': 9, 'price': 999}, {'gdscode': 1, 'price': 100},
            {'gdscode': 1, 'price': 200}]}})
    result = client(handler).quotes(['1', '2'])
    assert result['found'] == 0
    assert result['rows'][0]['reason'] == 'conflicting_price_rows'
    assert result['rows'][1]['reason'] == 'price_not_found'


def test_net_price_unit_and_retrieval_date_come_from_supplier_response():
    def handler(request):
        if request.url.path.endswith('/user/login'):
            return login()
        rows = ([{'gdscode': 1, 'name': 'Cable', 'edizm': 'м', 'art': 'ABC'}]
                if request.url.path.endswith('/catalog') else [{'gdscode': 1, 'price': 100, 'pricewnds': 122}])
        return httpx.Response(200, json={'status': {'code': 200}, 'data': {'rows': rows}})
    result = client(handler).quotes(['ETM1'])
    quote = result['quotes'][0]
    assert quote['price'] == 100 and quote['unit'] == 'м'
    assert quote['price_includes_vat'] is False and quote['price_gross'] == 122
    assert quote['retrieved_at'] and quote['source_kind'] == 'supplier_api'
    assert 'session' not in quote['source'] and result['found'] == 1


def test_authentication_error_and_http_logging_do_not_disclose_secrets(caplog):
    def handler(request):
        raise httpx.ConnectError('unsafe password=test-password', request=request)
    with caplog.at_level(logging.INFO), pytest.raises(EtmError) as caught:
        client(handler).search('cable')
    assert 'test-password' not in str(caught.value)
    assert 'test-login' not in caplog.text and 'test-password' not in caplog.text


def test_successful_login_http_log_also_redacts_query_credentials(caplog):
    def handler(request):
        return login() if request.method == 'POST' else httpx.Response(
            200, json={'status': {'code': 200}, 'data': {'rows': []}})
    with caplog.at_level(logging.INFO):
        client(handler).search('cable')
    assert 'test-login' not in caplog.text and 'test-password' not in caplog.text
    assert 'test-session' not in caplog.text


def test_forbidden_session_refreshes_once_and_never_retries_forever():
    calls = []
    def handler(request):
        calls.append(request)
        return login() if request.method == 'POST' else httpx.Response(
            403, json={'status': {'code': 403}})
    with pytest.raises(EtmError, match='access_or_lookup_failed'):
        client(handler).search('cable')
    assert sum(r.method == 'GET' for r in calls) == 2
    assert sum(r.method == 'POST' for r in calls) == 2


def test_price_batches_follow_official_fifty_code_limit():
    price_calls = []
    def handler(request):
        if request.method == 'POST':
            return login()
        price_calls.append(request)
        return httpx.Response(200, json={'status': {'code': 200}, 'data': {'rows': []}})
    result = client(handler).quotes([str(i) for i in range(1, 102)])
    assert len(price_calls) == 3 and result['missing'] == 101
    assert all(len(r.url.path.split('/')[-2].split(',')) <= 50 for r in price_calls)


def test_failed_access_invalidates_previous_connected_status():
    fail = [False]
    def handler(request):
        if request.method == 'POST':
            return login()
        return httpx.Response(403 if fail[0] else 200, json={
            'status': {'code': 403 if fail[0] else 200}, 'data': {'rows': []}})
    api = client(handler)
    api.probe()
    assert api.connected()
    fail[0] = True
    with pytest.raises(EtmError, match='access_or_lookup_failed'):
        api.probe()
    assert not api.connected()


def test_export_keeps_supplier_text_literal_and_missing_price_empty():
    from io import BytesIO
    from openpyxl import load_workbook
    from proxy.services.etm_supplier_service import quotes_to_xlsx
    rows = [{'code': '1', 'material': '=HYPERLINK("untrusted")', 'unit': 'м', 'price': 100,
             'source': 'https://ipro.etm.ru/api/v1/goods/1/price', 'retrieved_at': '2026-10-12T12:00:00Z'},
            {'code': '2', 'reason': 'price_not_found'}]
    book = load_workbook(BytesIO(quotes_to_xlsx({'rows': rows})))
    assert book.active['B2'].data_type == 's'
    assert book.active['D2'].value == 100
    assert book.active['D3'].value is None and book.active['J3'].value == 'Цена не найдена.'


@pytest.mark.parametrize('base', ['http://ipro.etm.ru/api/v1', 'https://other.test/api/v1',
                                 'https://ipro.etm.ru/api/v1?secret=value'])
def test_credentials_cannot_be_sent_to_an_unapproved_endpoint(base):
    with pytest.raises(EtmError, match='invalid_endpoint'):
        EtmConfig('test-login', 'test-password', base_url=base)
