import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from proxy.routers import service_sources as router
from proxy.security import require_user
from proxy.services import etm_supplier_service as etm
from proxy.services import runtime_config_registry_service as registry
from proxy.services import service_source_registry as sources


def test_etm_credentials_have_masked_gui_controls_without_restart(monkeypatch):
    monkeypatch.setenv('LES_ETM_LOGIN', 'hidden-operator')
    monkeypatch.setenv('LES_ETM_PASSWORD', 'hidden-password')
    registry.declared_env_defaults.cache_clear()
    for key in ('LES_ETM_LOGIN', 'LES_ETM_PASSWORD'):
        factor = registry._factor(key, {})
        assert factor['secret'] and factor['effective_value'] is None
        assert factor['mutable'] and not factor['restart_required']
        assert 'hidden-' not in str(factor)
    assert registry._factor('LES_ETM_ENABLED', {})['declared_default'] == '0'


@pytest.mark.parametrize('key,value', [('LES_ETM_ENABLED', 'bad'), ('LES_ETM_BASE_URL', 'https://other.test'),
                                     ('LES_ETM_TIMEOUT_SEC', 'nan'), ('LES_ETM_TIMEOUT_SEC', '0')])
def test_invalid_etm_settings_are_rejected_before_persistence(tmp_path, monkeypatch, key, value):
    path = tmp_path / '.env'
    monkeypatch.setattr(registry, 'env_path', lambda: path)
    with pytest.raises(registry.RuntimeConfigRegistryError, match='INVALID_VALUE'):
        registry.update_factors({key: value})
    assert not path.exists()


def test_configured_source_is_not_green_without_a_live_probe(tmp_path, monkeypatch):
    monkeypatch.setenv('LES_ETM_ENABLED', '1')
    monkeypatch.setenv('LES_ETM_LOGIN', 'hidden-operator')
    monkeypatch.setenv('LES_ETM_PASSWORD', 'hidden-password')
    monkeypatch.setattr(etm, '_SHARED_CLIENT', None)
    monkeypatch.setattr(sources, '_active_base_tokens', lambda: {})
    path = tmp_path / 'sources.yaml'
    path.write_text('sources:\n  - id: etm_supplier\n    status_if_missing: degraded\n', encoding='utf-8')
    source = sources.service_source('etm_supplier', path)
    assert source['status'] == 'missing_degraded'
    assert source['facts']['state'] == 'not_checked'
    assert 'hidden-' not in str(source)
    assert etm._SHARED_CLIENT is None  # Status reads never initialize an HTTP client.


def test_quote_api_uses_application_client_and_returns_a_safe_error(monkeypatch):
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[require_user] = lambda: {'role': 'user'}
    monkeypatch.setattr(etm, 'get_client', lambda: (_ for _ in ()).throw(etm.EtmError('needs_credentials')))
    response = TestClient(app).post('/api/service-sources/etm/quotes', json={'codes': ['1']})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'needs_credentials'
    assert 'пароль' in response.json()['detail']['message']


def test_download_ui_preserves_snapshot_and_uses_the_existing_price_dataset_path(monkeypatch):
    from sovushka.pages import instrumenty
    downloaded, notices = [], []
    async def post(path, data):
        assert path == '/api/service-sources/etm/quotes' and data == {'codes': ['1', '2']}
        return {'schema': 'etm_supplier_quotes_v1', 'requested': 2, 'found': 1, 'missing': 1,
                'retrieved_at': '2026-10-12T12:00:00Z',
                'rows': [{'code': '1', 'material': 'Cable', 'unit': 'м', 'price': 100},
                         {'code': '2', 'reason': 'price_not_found'}]}
    monkeypatch.setattr(instrumenty, 'api_post', post)
    monkeypatch.setattr(instrumenty.ui, 'download', lambda content, filename: downloaded.append((content, filename)))
    monkeypatch.setattr(instrumenty.ui, 'notify', lambda message, **kwargs: notices.append((message, kwargs)))
    asyncio.run(instrumenty._download_etm_quotes('1, 2'))
    assert downloaded[0][0].startswith(b'PK') and downloaded[0][1] == 'Прайс_ЭТМ_2026-10-12.xlsx'
    assert '«Прайсы»' in notices[0][0] and notices[0][1]['type'] == 'warning'


def test_catalogue_ui_keeps_distinct_codes_and_shows_article_and_unit(monkeypatch):
    from sovushka.pages import instrumenty
    async def post(path, data):
        assert path == '/api/service-sources/etm/catalog' and data == {'query': 'ABC', 'rows': 20}
        return {'schema': 'etm_catalog_v1', 'rows': [
            {'code': '1', 'name': 'Кабель', 'article': 'ABC', 'unit': 'м'},
            {'code': '2', 'name': 'Кабель', 'article': 'ABC-2', 'unit': 'упак'}]}
    monkeypatch.setattr(instrumenty, 'api_post', post)
    monkeypatch.setattr(instrumenty.ui, 'notify', lambda *args, **kwargs: None)
    options = asyncio.run(instrumenty._search_etm_catalog('  ABC  '))
    assert set(options) == {'1', '2'}
    assert 'ABC-2' in options['2'] and 'упак' in options['2']
