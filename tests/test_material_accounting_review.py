from proxy.services import rim_lsr_trace_service as rim
from proxy.services.fgis_price_service import PriceBook


def _rows(monkeypatch):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {
        'name': 'Mount', 'unit': 'm', 'resources': [
            {'kind': 'material', 'code': 'R1', 'name': 'Cable', 'unit': 'm', 'per_unit': 4},
        ],
    })
    work = dict(source_row='S!1', title='Mount', norm_code='\u0413\u042d\u0421\u041d01-01-001-01', quantity=2, unit='m')
    resource = dict(source_row='S!2', title='Cable', norm_code='', quantity=8, unit='m',
                    decision_kind='resource', included_in='S!1', resource_action='included',
                    target_resource_code='R1')
    return work, resource


def test_missing_resource_unit_cannot_prove_inclusion(monkeypatch):
    work, resource = _rows(monkeypatch)
    resource['unit'] = ''
    result = rim.positions_from_visible_lsr_rows([work, resource])
    assert result['row_bindings'][1]['status'] != 'resource_bound'


def test_explicit_zero_resource_quantity_is_not_replaced(monkeypatch):
    work, resource = _rows(monkeypatch)
    resource['resource_quantity'] = 0
    result = rim.positions_from_visible_lsr_rows([work, resource])
    binding = result['row_bindings'][1]
    assert binding['status'] == 'resource_quantity_mismatch'
    assert binding['residual_quantity'] == 8
    assert binding['resource_bindings'][0]['quantity'] == 0


def test_material_validation_matches_actual_price_branch():
    row = dict(source_row='S!1', decision_kind='material', title='Cable', quantity=3,
               unit='m', resource_code='R1', norm_code='')
    prices = PriceBook([dict(code='R1', name='Cable', unit='m',
                            price_current_eff=12, price_current=-7)])
    trace = rim.build_lsr_trace_from_visible_rows([row], pricebook=prices)
    assert trace['row_bindings'][0]['status'] != 'material_bound'
    assert trace['sections'][0]['positions'][0]['summary']['mat'] >= 0
