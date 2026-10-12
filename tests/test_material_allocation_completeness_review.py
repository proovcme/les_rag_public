import pytest

from proxy.services import rim_lsr_trace_service as rim


@pytest.mark.parametrize('allocated', [0, 4])
def test_partial_resource_allocation_does_not_complete_source_row(monkeypatch, allocated):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {
        'name': 'Mount', 'unit': 'm', 'resources': [
            {'kind': 'material', 'code': 'R1', 'name': 'Cable', 'unit': 'm', 'per_unit': 4},
        ],
    })
    work = dict(source_row='S!1', title='Mount', norm_code='\u0413\u042d\u0421\u041d01-01-001-01',
                quantity=2, unit='m')
    resource = dict(source_row='S!2', title='Cable', norm_code='', quantity=8, unit='m',
                    decision_kind='resource', included_in='S!1', resource_action='included',
                    target_resource_code='R1', resource_quantity=allocated, resource_unit='m')
    trace = rim.build_lsr_trace_from_visible_rows([work, resource])
    assert trace['row_bindings'][1]['status'] != 'resource_bound'
    assert trace['summary']['bound_rows'] == 1
    assert trace['summary']['unbound_rows'] == 1
    assert trace['row_bindings'][1]['residual_quantity'] == 8 - allocated
    assert trace['row_bindings'][1]['resource_bindings'][0]['quantity'] == allocated


@pytest.mark.parametrize('allocated', [None, 18.18])
def test_documented_demand_conversion_is_not_applied_twice(monkeypatch, allocated):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {
        'name': 'Mount', 'unit': 'm', 'resources': [
            {'kind': 'material', 'code': 'R1', 'name': 'Tray', 'unit': 'kg', 'per_unit': 4},
        ],
    })
    work = dict(source_row='S!1', title='Mount', norm_code='ГЭСН01-01-001-01', quantity=6, unit='m')
    resource = dict(source_row='S!2', title='Tray', norm_code='', quantity=6, unit='m',
                    decision_kind='resource', included_in='S!1', resource_action='included',
                    target_resource_code='R1', conversion_factor=3.03,
                    conversion_unit='kg', conversion_source='manufacturer card')
    if allocated is not None:
        resource.update(resource_quantity=allocated, resource_unit='kg')
    binding = rim.positions_from_visible_lsr_rows([work, resource])['row_bindings'][1]
    assert binding['status'] == 'resource_bound'
    assert binding['resource_bindings'][0]['quantity'] == pytest.approx(18.18)
    assert binding['required_quantity'] == pytest.approx(18.18)


def test_unpriced_standalone_material_does_not_complete_source_row():
    row = dict(source_row='S!1', decision_kind='material', title='Cable',
               quantity=8, unit='m', norm_code='')
    trace = rim.build_lsr_trace_from_visible_rows([row])
    assert trace['row_bindings'][0]['status'] == 'material_price_missing'
    assert trace['summary']['bound_rows'] == 0
    assert trace['summary']['unbound_rows'] == 1
    assert trace['summary']['result_status'] == 'priced_partial'
    assert len(trace['sections'][0]['positions']) == 1
