"""Execute explicit model material decisions; never infer a parent or resource.

An inclusion consumes an existing resource quantity, without adding work or cost.
An exclusion removes a named norm material when the project supplies its own product;
without it a standalone material would count the same covering twice.
Standalone materials remain visible even when their price has not been provided.
"""
from __future__ import annotations

import math
from typing import Any

RESOURCE_FIELDS = (
    'resource_action', 'resource_code', 'target_resource_code', 'target_resource_id', 'resource_name',
    'resource_quantity', 'resource_unit', 'price_source_ref', 'replaced_by',
    'conversion_factor', 'conversion_unit', 'conversion_source',
)


def finite_number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(',', '.').replace(' ', ''))
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def account_material_rows(positions, bindings, *, pricebook=None):
    from proxy.services import rim_lsr_trace_service as rim
    from proxy.smeta_core.row_decision import included_reference

    consumed = {}
    # Действие адресует работу, нормативную ревизию и исходную строку/группу.
    # Два действия над одним ресурсом неоднозначны: снятый ресурс нельзя ни снять
    # повторно, ни распределять в него количество (аудит Codex 17.09).
    resource_actions = {}
    # Снятия применяются только после проверки решения о замене: пока связь, количество
    # или обоснование не доказаны, состав нормы остаётся прежним.
    pending_exclusions = []
    for binding in bindings:
        status = binding.get('status')
        if status not in {'resource_accounting_unverified', 'material_pricing_required'}:
            continue
        row = binding['source_row']
        if status == 'material_pricing_required':
            quantity = finite_number(row.get('quantity'))
            unit = str(row.get('unit') or '').strip()
            if quantity is None or not unit:
                binding['status'] = 'material_quantity_required'
                continue
            code = str(row.get('resource_code') or '').strip()
            # Явный отказ от поставки — исполненное решение, а не пробел в цене: при
            # демонтаже изделие не поставляется, и цены на него не бывает (проход 27,
            # 18.09). Способ отказа назван в контракте — replaced_by=not_required, и
            # проход 30 показал, что модель им пользуется, оставляя код изделия из
            # карточки: с явным отказом код заявкой на поставку не считается.
            refused = str(row.get('replaced_by') or '').strip() == 'not_required'
            if refused or (not code and str(row.get('material_review_status') or '').strip() == 'not_present'):
                binding['status'] = 'material_not_supplied'
                continue
            title = str(row.get('title') or '')
            resource = dict(kind='material', code=code, name=title, unit=unit, per_unit=1)
            price = pricebook.lookup(code) if pricebook is not None and code else None
            binding['status'] = 'material_price_missing'
            diagnostic = getattr(pricebook, 'lookup_diagnostic', lambda _code: {})(code) if pricebook is not None and code else {}
            if diagnostic.get('status') == 'ambiguous':
                binding['status'] = 'material_price_ambiguous'
                binding['price_diagnostic'] = diagnostic
            if price:
                # Display the exact selected catalogue item alongside the authored
                # project name. This is provenance, not a material substitution.
                resource['price_card_name'] = str(price.get('name') or '')
                # Do not multiply a price in tonnes by a quantity in pieces. A price per
                # «1000 м» for a row in «м» is the same physical unit with a multiplier.
                if rim._price_unit_scale(unit, price.get('unit')) is not None:
                    current = rim._num(price.get('price_current'))
                    base = rim._num(price.get('price_base'))
                    index = rim._num(price.get('index'))
                    selected = current if current is not None else (
                        base * index if base is not None and index is not None else price.get('price_current_eff'))
                    value = finite_number(selected)
                    if value is not None:
                        binding['status'] = 'material_bound'
                    else:
                        resource['code'] = ''
                        resource['requested_resource_code'] = code
                else:
                    binding['status'] = 'material_price_unit_conflict'
                    resource['code'] = ''
                    resource['requested_resource_code'] = code
            position = dict(code='', name=title, unit=unit, qty=quantity,
                            work_id=str(row.get('work_id') or binding['row']),
                            source_row=binding['row'], section=str(row.get('section') or 'Материалы'),
                            resources=[resource], nr_pct=0, sp_pct=0, material_only=True)
            positions.append(position)
            binding['position'] = dict(position)
            binding['resource_bindings'] = [dict(
                action='standalone', resource_code=code, resource_name=title,
                quantity=quantity, unit=unit, basis_ref='selected pricebook: exact code',
                reason=binding['status'],
            )]
            binding['reason'] = binding['message'] = (
                'самостоятельный материал: ' + binding['status'])
            continue

        reference = included_reference(row)
        parents = [p for p in positions if str(p.get('work_id') or '') == reference and not p.get('material_only')]
        if not parents:
            parents = [p for p in positions if str(p.get('source_row')) == reference and not p.get('material_only')]
        if len(parents) != 1:
            same_code = [p for p in positions if reference and p.get('code') == reference]
            binding['status'] = 'resource_parent_ambiguous' if len(parents) > 1 or len(same_code) > 1 else 'resource_parent_missing'
            binding['reason'] = binding['message'] = 'нужен идентификатор конкретной строки работы: ' + reference
            continue
        parent = parents[0]
        parent_bindings = [b for b in bindings if
                           str(b.get('work_id') or b.get('row')) == str(parent.get('work_id') or parent['source_row'])]
        if len(parent_bindings) != 1 or parent_bindings[0].get('status') != 'bound':
            binding.update(status='resource_parent_unresolved', reason='расчёт указанной операции не подтверждён',
                           message='расчёт указанной операции не подтверждён')
            continue
        target = str(row.get('target_resource_code') or '').strip()
        action = str(row.get('resource_action') or '').strip().casefold()
        is_inclusion = action in {'included', 'включён', 'включен'}
        is_exclusion = action in {'excluded', 'исключён', 'исключен'}
        selector = _cell(row.get('target_resource_id'))
        if not (is_inclusion or is_exclusion) or not (target or selector):
            binding['reason'] = binding['message'] = (
                'нужны resource_action=included или excluded и target_resource_id либо однозначный target_resource_code из состава нормы')
            continue
        _, resources = rim._position_resources(parent)
        # Снимать можно материал и машину; распределять количество — только в материал.
        # Труд — ядро нормы: если он не подходит, модель выбирает другую норму (решение 17.09).
        allowed_kinds = EXCLUDABLE_KINDS if is_exclusion else {'material'}
        resource, problem = _resolve_target(parent, resources, selector, target, allowed_kinds)
        if problem:
            binding.update(status=problem, reason=problem, message=problem + ': ' + (selector or target))
            continue
        target = str(resource.get('code') or '')
        target_fact = _target_fact(parent, resource, selector)
        action_key = _action_key(parent, resource)
        previous_action = resource_actions.get(action_key)
        if previous_action == 'excluded' or (is_exclusion and previous_action):
            binding.update(status='resource_action_conflict', reason='', message=(
                f'над ресурсом {target} уже выполнено действие {previous_action}; '
                'второе действие над тем же ресурсом неоднозначно'))
            continue
        resource_actions[action_key] = 'excluded' if is_exclusion else 'included'
        if is_exclusion:
            # Материал нормы стоит деньгами как проектный: живой прогон 14–15.09, АР!1.31 —
            # 26 197,17 ₽ «Плитки ПВХ 1,2 мм» на строку ковровой плитки. Снятие проверяется
            # после всех операций: заменяющая поставка может стоять ниже в таблице модели.
            pending_exclusions.append((binding, row, parent, target, resource, reference))
            binding.update(status='resource_exclusion_unreplaced',
                           message='снятие ресурса ожидает проверки решения о замене')
            continue
        demand, demand_trace = rim._norm_qty_from_visible_row(row, '', {'unit': resource.get('unit')})
        if not str(row.get('unit') or '').strip() or demand is None or not math.isfinite(demand) or demand < 0:
            binding.update(status='resource_source_quantity_unverified', quantity_trace=demand_trace)
            continue
        resource_qty = row.get('resource_quantity')
        explicit_allocation = resource_qty not in (None, '')
        if resource_qty in (None, ''):
            resource_qty = row.get('quantity')
        physical = dict(row, quantity=resource_qty, unit=row.get('resource_unit') or row.get('unit'))
        if explicit_allocation:
            # Allocation is already expressed in resource_unit. Convert the
            # original demand separately; applying its factor twice overcounts.
            physical = {key: value for key, value in physical.items() if not key.startswith('conversion_')}
        if not str(physical.get('unit') or '').strip():
            binding['status'] = 'resource_unit_required'
            continue
        quantity, quantity_trace = rim._norm_qty_from_visible_row(physical, '', {'unit': resource.get('unit')})
        if quantity is None or not math.isfinite(quantity) or quantity < 0:
            binding['status'] = 'resource_unit_conflict'
            binding['quantity_trace'] = quantity_trace
            continue
        key = action_key
        consumption = finite_number(resource.get('per_unit'))
        if consumption is None:
            binding.update(status='resource_quantity_unknown', reason='исходный расход ресурса неизвестен; доступное количество не установлено',
                           message='исходный расход ресурса неизвестен; доступное количество не установлено')
            continue
        available = consumption * float(parent['qty'])
        available *= (parent.get('resource_coefficients') or {}).get('material', 1.0)
        if consumed.get(key, 0) + quantity > available + 1e-9:
            binding['status'] = 'resource_quantity_exceeded'
            binding['reason'] = binding['message'] = f'заявлено {quantity}; остаток ресурса {available - consumed.get(key, 0):g}'
            continue
        consumed[key] = consumed.get(key, 0) + quantity
        complete = math.isclose(quantity, demand, rel_tol=1e-9, abs_tol=1e-9)
        binding.update(status='resource_bound' if complete else 'resource_quantity_mismatch',
                       source_quantity_trace=demand_trace, required_quantity=demand,
                       residual_quantity=max(0, demand - quantity),
                       covered_by_work_id=str(parent.get('work_id') or parent['source_row']),
                       quantity_trace=quantity_trace, reason=str(row.get('coverage') or row.get('analogue') or ''),
                       resource_bindings=[dict(action='included', resource_code=target,
                           **target_fact,
                           resource_name=resource.get('name'), quantity=quantity, unit=resource.get('unit'),
                           reason='в пределах существующего ресурса; повторная стоимость не добавлена',
                           basis_ref=reference)])
        if not complete:
            binding['reason'] = binding['message'] = (
                f'потребность строки {demand:g}; связано {quantity:g}; единица {resource.get("unit")}; '
                'полный учёт строки не подтверждён')
    _apply_exclusions(pending_exclusions, bindings, rim)
    return {'positions': positions, 'row_bindings': bindings}


EMPTY_CELLS = {'', '—', '–', '-'}
EXCLUDABLE_KINDS = {'material', 'machine'}
NOT_REQUIRED = 'not_required'


def _cell(value):
    text = str(value or '').strip()
    return '' if text in EMPTY_CELLS else text


def _target_fact(parent, resource, selector=''):
    from proxy.smeta_core.resource_identity import resource_selector
    fields = {key: resource[key] for key in ('source_resource_ids', 'source_resource_group_id') if key in resource}
    if fields:
        fields['target_resource_id'] = selector or resource_selector(resource)
        fields['normative_identity'] = parent.get('normative_identity')
    return fields


def _action_key(parent, resource):
    from proxy.smeta_core.resource_identity import resource_selector, resource_dedupe_key
    pin = parent.get('normative_identity') or {}
    return (str(parent.get('work_id') or parent['source_row']), pin.get('base_sha256'),
            pin.get('norm_id'), resource.get('source_resource_group_id') or resource_selector(resource)
            or resource_dedupe_key(resource))


def _resolve_target(parent, resources, selector, code, allowed_kinds):
    """Resolve authored addresses only; never choose a same-code substitute."""
    if selector.startswith('row:'):
        matches = [r for r in resources if selector[4:] in r.get('source_resource_ids', [])]
    elif selector.startswith('group:'):
        matches = [r for r in resources if r.get('source_resource_group_id') == selector]
    elif selector:
        return None, 'resource_target_missing'
    else:
        matches = [r for r in resources if str(r.get('code') or '') == code and r.get('kind') in allowed_kinds]
        if not matches and any(str(r.get('code') or '') == code and r.get('kind') not in allowed_kinds for r in resources):
            return None, 'resource_action_not_allowed'
    if len(matches) != 1:
        return None, 'resource_target_ambiguous' if matches else 'resource_target_missing'
    resource = matches[0]
    if code and str(resource.get('code') or '') != code:
        return None, 'resource_target_code_conflict'
    if resource.get('kind') not in allowed_kinds:
        return None, 'resource_action_not_allowed'
    ids = resource.get('source_resource_ids') or []
    if len(ids) > 1 and not selector.startswith('group:'):
        return None, 'resource_group_scope_required'
    if selector:
        pin = parent.get('normative_identity')
        proof = parent.get('resource_delivery_proof') or {}
        if not pin or proof.get('normative_identity') != pin:
            return None, 'target_resource_not_proven_delivered'
        def evidenced(item):
            return all(isinstance(item.get(k), str) and len(item[k]) == 64 for k in ('sha256', 'packet_sha256')) and bool(item.get('ref'))
        shown = {item.get('source_resource_id') for item in proof.get('rows', []) if evidenced(item)}
        if not ids or not set(ids).issubset(shown):
            return None, 'target_resource_not_proven_delivered'
        if selector.startswith('group:') and not any(
            item.get('source_resource_group_id') == selector and
            set(item.get('source_resource_ids') or []) == set(ids) and evidenced(item)
            for item in proof.get('groups', [])
        ):
            return None, 'target_resource_not_proven_delivered'
    return resource, ''


def _exclude_resource(parent, resource, rim):
    _, resources = rim._position_resources(parent)
    selected = _action_key(parent, resource)
    parent['resources'] = [
        dict(item, per_unit=0, excluded=True, excluded_per_unit=item.get('per_unit'))
        if _action_key(parent, item) == selected
        else item
        for item in resources
    ]


def _apply_exclusions(pending, bindings, rim):
    """Проверить решение модели о замене каждого снятого ресурса и только затем снять его.

    Замена — явная связь `replaced_by` на операцию самостоятельного материала той же
    исходной строки с количеством больше нуля; одна поставка заменяет один ресурс.
    Отсутствие потребности — `replaced_by=not_required` с обоснованием в coverage, например
    при демонтаже. Без решения, с неверной связью или без обоснования состав нормы не
    меняется. Код не выбирает изделие и не требует равенства количеств: снятое и
    поставленное количество записываются рядом, их соотношение проверяет модель и приёмка
    (проверка Codex 17.09: поставка 0 м² вместо снятых 102 м² давала priced_final).
    """
    supplies = {str(b.get('work_id')): b for b in bindings
                if any(item.get('action') == 'standalone' for item in (b.get('resource_bindings') or []))}
    used = {}
    for binding, row, parent, target, resource, reference in pending:
        link = _cell(row.get('replaced_by'))
        reason = _cell(row.get('coverage')) or _cell(row.get('not_covered'))
        coefficient = (parent.get('resource_coefficients') or {}).get(resource.get('kind'), 1.0)
        consumption = finite_number(resource.get('per_unit'))
        excluded_quantity = round(consumption * float(parent['qty']) * coefficient, 6) if consumption is not None else None
        item = dict(action='excluded', resource_code=target, resource_name=resource.get('name'),
                    **_target_fact(parent, resource, _cell(row.get('target_resource_id'))),
                    quantity=0, unit=resource.get('unit'), basis_ref=reference,
                    excluded_quantity=excluded_quantity, excluded_per_unit=consumption, excluded_unit=resource.get('unit'),
                    replaced_by=link or None)
        work = str(parent.get('work_id') or parent['source_row'])
        binding.update(covered_by_work_id=work, reason=reason, resource_bindings=[item])
        if not link:
            binding.update(status='resource_exclusion_unreplaced', message=(
                f'ресурс нормы {target} не снят: нет решения о замене — replaced_by=work_id поставки '
                'или not_required с обоснованием'))
            continue
        if link.casefold() == NOT_REQUIRED:
            if not reason:
                binding.update(status='resource_exclusion_unjustified', message=(
                    f'ресурс нормы {target} не снят: not_required требует обоснования в coverage'))
                continue
            _exclude_resource(parent, resource, rim)
            binding.update(status='resource_excluded',
                           message=f'ресурс нормы {target} снят: изделие не требуется — {reason}')
            continue
        supply = supplies.get(link)
        problem = ''
        quantity = None
        if resource.get('kind') == 'machine':
            # Машину нечем заменить поставкой материала: снять её можно только как ненужную.
            problem = 'машину нельзя заменить поставкой материала; укажите not_required с обоснованием'
        elif supply is None:
            problem = f'операция {link} не найдена или не является самостоятельным материалом'
        elif str(supply.get('row')) != str(binding.get('row')):
            problem = f'операция {link} относится к другой исходной строке'
        else:
            supplied = (supply.get('resource_bindings') or [{}])[0]
            quantity = finite_number(supplied.get('quantity'))
            if not quantity:
                problem = f'количество заменяющей операции {link} должно быть больше нуля'
            elif link in used:
                problem = f'операция {link} уже заменяет ресурс {used[link]}'
        if problem:
            binding.update(status='resource_exclusion_replacement_invalid',
                           message=f'ресурс нормы {target} не снят: {problem}')
            continue
        used[link] = target
        _exclude_resource(parent, resource, rim)
        item.update(replacement_quantity=quantity, replacement_unit=supplied.get('unit'))
        binding.update(status='resource_excluded',
                       message=f'ресурс нормы {target} снят и заменён операцией {link}')
