"""Serializable calculation facts for the same model's next authored revision."""
from __future__ import annotations

import hashlib
import json


def _norm_resource_index(trace, positions):
    """Ресурсы норм строки: код -> чья это норма и как называется ресурс.

    Проход 13 (18.09): в поставку кабеля модель поставила код изоляционной ленты из состава
    той же нормы, и «изделие» посчиталось по цене ленты. Совпадение кода — проверяемый факт,
    и чек его называет; выбор кода остаётся за моделью.
    """
    work_rows = {str(binding.get('work_id') or binding.get('row')): str(binding.get('row'))
                 for binding in trace.get('row_bindings') or []}
    index = {}
    for work_id, position in positions.items():
        # Строка берётся из самой позиции: она известна расчёту и не зависит от того,
        # попала ли работа в список привязок этого прохода.
        source_row = str(position.get('source_row') or '') or work_rows.get(work_id, '')
        # Позиция без шифра нормы — это сам материал строки: он не «ресурс нормы» себе
        # самому, и такая подсказка была ложной (проход 15, 18.09).
        if not str(position.get('norm_code') or '').strip():
            continue
        for resource in position.get('resources') or []:
            code = str(resource.get('code') or '').strip()
            if code:
                index.setdefault((source_row, code), {
                    'work_id': work_id,
                    'norm_code': str(position.get('norm_code') or ''),
                    'name': str(resource.get('name') or ''),
                })
    return index


def calculation_receipts(trace, *, pricebook=None, pricebook_name=''):
    positions = {}
    for section in trace.get('sections') or []:
        for position in section.get('positions') or []:
            work = next((row for row in position.get('rows') or [] if row.get('type') == 'work'), {})
            meta = work.get('meta') or {}
            resources = []
            for row in position.get('rows') or []:
                if not str(row.get('type') or '').startswith('resource_'):
                    continue
                columns = row.get('columns') or {}
                code = columns.get('2', '')
                card = pricebook.lookup(code) if pricebook is not None and code else None
                resources.append(dict(kind=(row.get('meta') or {}).get('kind'),
                    **{key: row['meta'][key] for key in ('source_resource_ids', 'source_resource_group_id',
                       'normative_identity', 'excluded', 'excluded_per_unit', 'normative_price',
                       'price_record_identity') if key in (row.get('meta') or {})},
                    code=code, name=columns.get('3'), unit=columns.get('4'),
                    per_unit=columns.get('5'), coefficient=columns.get('6'), quantity=columns.get('7'),
                    known_cost=columns.get('12'), price_source=row.get('source'),
                    price_action=(row.get('meta') or {}).get('price_action'),
                    price_card={key: card[key] for key in (
                        'code', 'name', 'unit', 'price_base', 'price_current', 'index', 'price_current_eff'
                    ) if key in card} if card else None))
            positions[str(meta.get('work_id') or meta.get('source_row'))] = dict(
                source_row=str(meta.get('source_row') or ''),
                work_name=str((work.get('columns') or {}).get('3') or ''),
                norm_code=(work.get('columns') or {}).get('2', ''),
                normative_source=meta.get('normative_source'),
                quantity_trace=meta.get('quantity_trace'), resources=resources,
                summary={key: position['summary'][key] for key in (
                    'ozp', 'em', 'mat', 'known_amount', 'full_amount', 'labor_qty',
                    'machinist_qty', 'completeness_reasons') if key in position.get('summary', {})},
                nr_sp=_nr_sp_fact(position.get('summary', {}).get('nr_sp_trace')))
    norm_resources = _norm_resource_index(trace, positions)
    removals = _removal_work_index(positions)
    receipts = []
    for binding in trace.get('row_bindings') or []:
        work_id = str(binding.get('work_id') or binding.get('row'))
        fact = dict(source_row=str(binding.get('row')), work_id=work_id,
            status=str(binding.get('status') or 'unresolved'),
            pricebook=dict(name=pricebook_name, region=getattr(pricebook, 'region', ''),
                           period=getattr(pricebook, 'quarter', ''),
                           **({'identity': getattr(pricebook, 'identity', None),
                               'document_basis': trace['document_price_basis']}
                              if 'document_price_basis' in trace else {})),
            calculation=positions.get(work_id),
            covered_by_work_id=binding.get('covered_by_work_id'),
            resource_bindings=[_with_row_facts(item, norm_resources, removals, str(binding.get('row')), work_id)
                               for item in binding.get('resource_bindings') or []],
            reason=binding.get('message') or binding.get('reason') or '')
        if binding.get('normative_revision'):
            fact['normative_revision'] = binding['normative_revision']
        if trace.get('price_basis_conflict'):
            fact['price_basis_conflict'] = trace['price_basis_conflict']
        parent = positions.get(str(binding.get('covered_by_work_id') or ''))
        if parent:
            fact['parent_normative_source'] = parent['normative_source']
            for allocation in fact['resource_bindings']:
                matching = [r for r in parent['resources'] if
                    (r.get('source_resource_ids') == allocation['source_resource_ids']
                     if allocation.get('source_resource_ids') else r['code'] == allocation.get('resource_code'))]
                if len(matching) == 1:
                    calculated = matching[0]
                    allocation['parent_resource_quantity'] = calculated['quantity']
                    allocation['parent_resource_known_cost'] = calculated['known_cost']
                    allocation['allocated_known_cost'] = (
                        round(calculated['known_cost'] * allocation['quantity'] / calculated['quantity'], 2)
                        if calculated.get('quantity') and calculated.get('known_cost') is not None else None)
                    allocation['added_cost'] = 0
        # Операция без шифра нормы и без поставки: расчёт отвергнет строку (проход 24,
        # 18.09 — «Снятие оповещателя» подтверждено по чеку и отклонено как
        # norm_selection_required). Подтверждать нечего, и чек называет пробел.
        # Только работа: у поставки нормы не бывает, и та же подсказка сбивала решение
        # по изделию (проход 28, 18.09).
        if (fact.get('calculation')
                and not str(fact['status']).startswith('material')
                and not str((fact['calculation'] or {}).get('norm_code') or '').strip()
                and not fact['resource_bindings']):
            fact['norm_code_missing'] = True
        # The receipt is a fact about inputs/result, never a model approval.
        fact['calculation_ref'] = hashlib.sha256(json.dumps(_reviewed_part(fact), ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        receipts.append(fact)
    return receipts


# Выбор норматива НР/СП — отдельное решение модели по каталогу, а не пересмотр состава
# расчёта. Если бы он входил в calculation_ref, строка с подтверждённым составом после
# выбора норматива уходила бы на лишний проход подтверждения (живая проверка 17.09).
_OVERHEAD_DEPENDENT = ('nr_sp', 'known_amount', 'full_amount')


_REMOVAL_WORDS = ('демонтаж', 'снятие', 'разборка', 'демонтир')


def _removal_work_index(positions):
    """Строки, чья работа — демонтаж: вид работы читается из наименования нормы.

    Проход 22 (18.09): к демонтажу оповещателя модель добавила сам оповещатель по цене
    нового. Нужно ли изделие, решает модель; факт вида работы называет чек.
    """
    index = {}
    for work_id, position in positions.items():
        name = str(position.get('work_name') or '')
        if any(word in name.casefold() for word in _REMOVAL_WORDS):
            index.setdefault(str(position.get('source_row') or ''), {
                'work_id': work_id,
                'norm_code': str(position.get('norm_code') or ''),
                'name': name,
            })
    return index


def _with_row_facts(binding, norm_resources, removals, source_row, work_id=''):
    """Связка с проверяемыми фактами строки: ресурс нормы и вид работы."""
    item = _with_norm_resource_hint(binding, norm_resources, source_row, work_id)
    removal = removals.get(source_row)
    if removal and removal.get('work_id') != work_id and str(item.get('action') or '') == 'standalone':
        item['row_work_is_removal'] = dict(removal)
    return item


def _with_norm_resource_hint(binding, norm_resources, source_row, work_id=''):
    """Копия связки; у самостоятельного материала называется совпадение с ресурсом нормы."""
    item = dict(binding or {})
    code = str(item.get('resource_code') or '').strip()
    hint = norm_resources.get((source_row, code)) if code else None
    if hint and hint.get('work_id') != work_id and str(item.get('action') or '') == 'standalone':
        item['matches_norm_resource'] = dict(hint)
    return item


def _nr_sp_fact(trace):
    trace = trace if isinstance(trace, dict) else {}
    fact = {key: trace.get(key) for key in ('status', 'rule_id', 'label', 'nr_pct', 'sp_pct') if key in trace}
    if trace.get('candidates'):
        fact['candidates'] = [{key: item.get(key) for key in ('rule_id', 'label', 'nr_pct', 'sp_pct')}
                              for item in trace['candidates'] if isinstance(item, dict)]
    return fact


def _reviewed_binding(binding):
    """Связка ресурса без собственной формулировки модели: код задаёт личность ресурса.

    Проход 8 (17.09): модель переписала название материала, хэш чека сменился, и
    подтверждение не сходилось никогда. Переименование — не изменение расчёта; без кода
    имя остаётся единственной личностью и продолжает участвовать.
    """
    item = dict(binding or {})
    if str(item.get('resource_code') or item.get('target_resource_id') or '').strip():
        item.pop('resource_name', None)
    return item


def _reviewed_part(fact):
    fact = {**fact, 'resource_bindings': [_reviewed_binding(item)
                                          for item in (fact.get('resource_bindings') or [])]}
    if isinstance((fact.get('pricebook') or {}).get('document_basis'), dict):
        basis = fact['pricebook']['document_basis']
        fact['pricebook'] = {**fact['pricebook'], 'document_basis':
                            {key: basis.get(key) for key in ('status', 'identity')}}
    calculation = fact.get('calculation')
    if not isinstance(calculation, dict):
        return fact
    summary = {key: value for key, value in (calculation.get('summary') or {}).items()
               if key not in _OVERHEAD_DEPENDENT}
    if 'completeness_reasons' in summary:
        summary['completeness_reasons'] = [reason for reason in summary['completeness_reasons']
                                           if reason != 'nr_sp_unresolved']
    reviewed = {key: value for key, value in calculation.items() if key not in _OVERHEAD_DEPENDENT}
    return {**fact, 'calculation': {**reviewed, 'summary': summary}}


def receipt_context(receipts):
    if not receipts:
        return ''
    return ('Результаты расчёта сохранённых решений (это не подтверждение пригодности нормы). '
            'Проверь операции, труд, машины, материалы и выбранные связи по этим фактам; '
            'название price_card относится к ценовому справочнику, а name — к выбранному ресурсу. '
            'Различие назначения должен оценить ты. included не добавляет повторную стоимость. '
            'Если состав и влияние подходят, верни полный набор операций строки с '
            'resource_review_status=keep_all_confirmed, а в resource_review_ref — значение calculation_ref '
            'этой операции из фактов ниже, скопированное целиком, а не само слово. Подтверждение нужно '
            'каждой операции, у которой ниже есть свой чек, включая самостоятельный материал и поставку: '
            'у каждой берётся её собственный calculation_ref. Работа без своей поставки не закрывает строку. '
            'Когда в той же строке ты отмечаешь непокрытое (not_covered), общего подтверждения '
            'недостаточно: добавь material_review_status (confirmed, not_present, unresolved '
            'или rejected) и material_review_reason — почему выбранный состав применим к этому '
            'изделию несмотря на пометку. Без этого строка останется открытой. '
            'Учитывай цену подтверждения: материалы нормы остаются в смете с их ценами. '
            'matches_norm_resource у самостоятельного материала означает, что названный код — это ресурс '
            'нормы той же строки, а не изделие из ведомости: проверь, то ли изделие ты назвал. '
            'row_work_is_removal означает, что работа этой строки — демонтаж или снятие: при демонтаже '
            'изделие обычно не поставляется. Либо объясни в material_review_reason, зачем оно здесь нужно, '
            'либо убери операцию поставки — строку самостоятельного материала с этим resource_code. '
            'Работу строки при этом отвергать не нужно: она проверяется своим чеком. '
            'norm_code_missing означает, что у операции нет шифра нормы: подтверждение такой операции '
            'строку не закроет. Выбери подходящую норму либо сохрани незавершённую работу: '
            'те же source_row и work_id, исходные объём и единицу, norm_code пустым, '
            'decision_kind=уточнение и конкретную причину в coverage. '
            'Если ты отверг прежнюю норму, отрази отказ в таблице: очисти её norm_code, '
            'evidence_refs, resource_review_status и resource_review_ref; пояснение под таблицей '
            'не изменяет расчёт. Старую норму и её подтверждение не переноси в новое решение. '
            'Если операция нормы подходит, а её материал — не изделие этой строки, сними этот '
            'материал: отдельной операцией с included_in=work_id работы, resource_action=excluded '
            'и target_resource_code снимаемого ресурса, а изделие строки добавь ещё одной '
            'операцией как самостоятельный материал и свяжи их: replaced_by=work_id этой поставки. '
            'Если изделие не требуется (например, демонтаж), укажи replaced_by=not_required и '
            'обоснование в coverage. Так же снимается ненужная машина нормы — только с not_required; '
            'труд нормы не снимается: если он не подходит, выбери другую норму. '
            'Без такого решения ресурс не снимается. '
            'Без снятия покрытие будет посчитано дважды. '
            'Если не подходит и сама операция — это не подтверждение: верни '
            'material_review_status=rejected или выбери другую норму. '
            'Если не подходят, измени своё решение; изменённый расчёт требует новой проверки. '
            'Если у работы nr_sp.status не resolved, выбери норматив накладных расходов и сметной '
            'прибыли из nr_sp.candidates по виду работ и верни его rule_id в колонке nr_sp_rule_id; '
            'код не выбирает норматив за тебя, а чужое для сборника правило отвергает. '
            'Выбор норматива не меняет calculation_ref.\n'
            + json.dumps(receipts, ensure_ascii=False, separators=(',', ':')))


def declares_non_coverage(row) -> bool:
    """True, когда автор решения сам записал, что часть работы или изделия не покрыта.

    Поле `not_covered` предусмотрено контрактом, но модель до сих пор писала то же
    утверждение префиксом внутри `coverage` (живой прогон 14–15.09: поле пустое у всех
    198 строк, префикс — у 31). Оба вида — одно и то же утверждение автора.
    """
    if str((row or {}).get('not_covered') or '').strip():
        return True
    return 'not_covered' in str((row or {}).get('coverage') or '')


def material_review_holds(row) -> bool:
    """True, когда подтверждение расчёта не противоречит пометкам своего же автора.

    `keep_all_confirmed` — один ответ на весь расчёт, и он молча проставлял «подтверждено»
    труду, машинам и материалам разом. Так закрылась АР!1.31 «Ковровая плитка Atlas 05»
    по норме на ПВХ-плитки с её же пометкой «материал ковровая плитка vs ПВХ».

    Код не выбирает норму за модель и не объявляет её негодной: строка остаётся открытой
    и вернётся к модели со своим чеком. Снять отказ модель может сама — явным
    `material_review_status` с обоснованием, это по-прежнему её решение.
    """
    status = str((row or {}).get('material_review_status') or '').strip()
    if status:
        return status == 'confirmed'
    return not declares_non_coverage(row)


def apply_model_review(trace, receipts, decisions):
    """Keep a calculated preview open until its exact facts are model-confirmed.

    No model call here: the next ordinary chat turn carries the receipt.
    """
    authored = {str(row.get('work_id') or row.get('source_row') or index): row
                for index, row in enumerate(decisions, 1)}
    pending = set()
    for binding, receipt in zip(trace.get('row_bindings') or [], receipts):
        row = authored.get(receipt['work_id'], {})
        if binding.get('status') not in {'bound', 'material_bound', 'resource_bound'}:
            continue
        # Точную ссылку нельзя получить, не прочитав именно этот расчёт, поэтому она и есть
        # подтверждение. Отдельная колонка статуса рядом с ней ничего не добавляла, а на
        # широкой таблице модель сдвигала ячейки и строка не закрывалась (проход 11, 18.09).
        # Явный отказ и собственные пометки автора по-прежнему сильнее ссылки.
        status = str(row.get('resource_review_status') or '').strip()
        confirmed = (row.get('resource_review_ref') == receipt['calculation_ref']
                     and status in {'', 'keep_all_confirmed'}
                     and material_review_holds(row))
        # Ресурс собственной нормы, названный изделием ведомости, закрывал строку молча:
        # кабель посчитался по цене изоляционной ленты (проход 15, 18.09). Код не выбирает
        # код за модель, но требует её объяснения — это по-прежнему её решение.
        norm_resource = next((item.get('matches_norm_resource')
                              for item in receipt.get('resource_bindings') or []
                              if item.get('matches_norm_resource')), None)
        explained = str(row.get('material_review_reason') or '').strip()
        if confirmed and norm_resource and not explained:
            confirmed = False
            binding['resource_review_reason'] = (
                'кодом изделия назван ресурс нормы «' + str(norm_resource.get('name') or '') + '» '
                'работы ' + str(norm_resource.get('norm_code') or '') + '; назови в material_review_reason, '
                'почему это изделие строки, либо укажи код самого изделия')
            binding['resource_review_status'] = 'required'
            binding['status'] = 'resource_review_required'
            binding['message'] = binding['resource_review_reason']
            receipt['status'] = 'resource_review_required'
            pending.add(receipt['work_id'])
            continue
        binding['resource_review_status'] = 'keep_all_confirmed' if confirmed else 'required'
        binding['resource_review_reason'] = 'calculation_ref: ' + receipt['calculation_ref']
        if not confirmed:
            pending.add(receipt['work_id'])
            binding.update(status='resource_review_required',
                message='модель должна проверить фактический расчёт и resource_review_ref',
                resource_review_reason='следующий обычный проход; calculation_ref: ' + receipt['calculation_ref'])
            receipt['status'] = 'resource_review_required'
    # The allocation cannot be final before its parent operation is reviewed.
    for binding, receipt in zip(trace.get('row_bindings') or [], receipts):
        if binding.get('status') == 'resource_bound' and binding.get('covered_by_work_id') in pending:
            binding['status'] = receipt['status'] = 'resource_parent_review_required'
    if not pending:
        return
    from proxy.smeta_core.row_decision import aggregate_operation_statuses, operation_executed, row_accounted, source_resolved, decision_resolved
    statuses = aggregate_operation_statuses(receipts) or {}
    summary = trace['summary']
    summary['resource_review_required_operations'] = len(pending)
    summary.update(full_amount=None, amount_status='partial', result_status='priced_partial',
        bound_rows=sum(row_accounted(status) for status in statuses.values()))
    summary['bound_operations'] = sum(operation_executed(r['status']) for r in receipts)
    summary['non_work_rows'] = sum(status == 'section_recognized' for status in statuses.values())
    summary['resolved_source_rows'] = sum(source_resolved(status) for status in statuses.values())
    summary['unbound_operations'] = sum(not decision_resolved(r['status']) for r in receipts)
    summary['unbound_rows'] = len(statuses) - summary['resolved_source_rows']
    for section in trace.get('sections') or []:
        for position in section.get('positions') or []:
            rows = position.get('rows') or []
            work = next((r for r in rows if r.get('type') == 'work'), {})
            if str((work.get('meta') or {}).get('work_id')) not in pending:
                continue
            position['summary'].update(full_amount=None, amount_status='partial')
            for row in rows:
                if row.get('label') == 'Всего по позиции':
                    row['label'] = row['columns']['3'] = 'Известная стоимость позиции'
