# Диалоговая РИМ-сессия

Статус: реализован Mac-кандидат 0.26.1. Модуль расширяет `smeta_core`, не создаёт
второй сметный движок и не меняет профессиональные решения модели или сметчика.

## Поток

```text
XLSX/CSV
  → immutable source intake
  → ВОР revision
  → Qwen scope и batch catalog/search/read/submit
  → mapping revision → deterministic global review → user mapping lock
  → model/user-authored scenario
  → canonical RIM calculator → requirements
  → КАЦ/коэффициенты/уточнения → обязательный пересчёт
  → priced draft → user final lock → XLSX + audit
```

Состояние хранится в `storage/rim_sessions` как SQLite-граф append-only
ревизий. Запрос с устаревшим `expected_parent_revision_id` отклоняется, сессии
изолированы по владельцу, а административный доступ остаётся явным.

Mapping lock и final lock — разные пользовательские ревизии. Закрытие
requirement не обновляет старую расчётную трассу и не разрешает финализацию:
новый `priced_draft` появляется только после повторного детерминированного
расчёта.

## Строгий нормативный контракт

Для диалоговой РИМ-сессии разрешена только цепочка:

```text
browse_norm_catalog
  → search_norms_batch
  → read_norms_batch
  → submit_lsr_mapping
```

Qwen обязан сначала выбрать для строки ВОР `base_types` и `collections`.
`search_norms_batch` принимает только `scope_mode=scoped`; глобальный либо
неполный scope отклоняется до retrieval. `SmetaNormToolSession` дополнительно
проверяет, что этот scope был открыт через `browse_norm_catalog`, и только
затем передаёт фильтры в `browse_norms_many()` — SQLite FTS/Qdrant RRF/rerank.
Старый текстовый `estimate_harness_service.search_norm()` не является точкой
входа этого модуля.

Shortlist из RAG имеет роль навигации. Он может дать Qwen `norm_key`,
technology hints и `questions_to_ask`, но не является расчётным evidence.
Выбранная строка проходит только после `read_norms_batch`: mapping хранит
`card_opened=true`, `norm_source_ref`, редакцию и identity целиком прочитанной
карточки versioned structured store. Норма без открытой карточки блокирует
mapping lock и расчёт.

`questions_to_ask` из навигационной карточки передаются Qwen отдельным
ограниченным ходом. Модель выбирает один наиболее ценный вопрос, формулирует
его по-русски и сохраняет как открытый вопрос сессии. В UI варианты ответа
показаны кликабельными кнопками; свободный текст тоже допустим. Короткий
следующий ответ интерпретируется относительно этого вопроса, а не запускает
новый workflow.

Для локальной Qwen 3.5 9B преобразование спецификации начинается с bounded
transport-пакета в 5 исходных позиций. В первом действии доступен только
`draft_work_schedule`; вопрос разрешается после сохранения source-linked
черновика. Это ограничение транспортного контекста, а не автоматический выбор
работ кодом.

## Расчёт и сценарии

Код не строит Cartesian product профессиональных альтернатив. Он показывает
теоретическое число комбинаций и считает только совместимый сценарий,
составленный моделью или пользователем. Лимит по умолчанию — 1000; превышение
возвращается как blocking issue.

Сценарий преобразуется в canonical visible rows и передаётся
`smeta_core.application.calculate_visible_rows_revision`. Пропущенная цена
читается из exact resource trace и создаёт blocking `kac`, а не нулевую цену.
Имеющийся РИМ renderer строит графы 1–12; дополнительными листами идут
`Недостающие данные` и `Аудит`.

## API и UI

Роутер `proxy/routers/rim.py` предоставляет owner-scoped `/api/rim/sessions/*`:
сессии и ревизии, импорт/ВОР, model tools и agent turn, mapping/XLSX/global
review/lock, сценарии и расчёт (`/combinations/calculate` или `/recalculate`),
requirements, final lock, export и audit.

NiceGUI-поверхность `sovushka/pages/rim.py` доступна как lazy-вкладка
«РИМ-смета». Она использует общий UI kit и показывает источник, ревизию,
основание, статус и блокировки для ВОР, mapping, review, requirements, ЛСР и
финализации. Список owner-scoped сессий позволяет вернуться к предыдущей
работе; отсутствующий либо устаревший сохранённый ID заменяется последней
доступной сессией без ложного `404`.

## Проверки кандидата

- unit/API/XLSX/state/UI тесты находятся в `tests/test_rim_*.py` и
  `tests/test_sovushka_uikit.py`;
- isolated Mac browser smoke проверен на desktop и 390 px без горизонтального
  переполнения;
- реальная `СКС.xlsx` распознана как спецификация: 70 позиций, 3 раздела,
  structural issues отсутствуют; после ужесточения draft-schema Qwen сохранил
  первые 5 строк с обязательными `work_name`, `unit`, `quantity`,
  `quantity_origin`, `source_ref` и задал технический вопрос «монтаж и
  подключение входят в ВОР или только поставка?» с двумя вариантами ответа;
- реальный Mac Qwen 3.5 9B первым вызовом выбрал `browse_norm_catalog`, не
  придумав шифр;
- полный live batch-loop одной строки не завершился за пять минут. Это
  открытый performance gate локальной модели, а не основание обходить строгую
  цепочку.

Legion и живые LES-сервисы этим кандидатом не изменялись.
