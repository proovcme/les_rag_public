# External Radar — радар внешних источников

Назначение: дать оператору быстрый обзор внешних папок и архивной карты перед in-place индексацией.
Это навигационный слой Самовара, а не evidence для ответа.

## Точки входа

- Сервис: `proxy/services/external_radar_service.py`.
- API: `GET /api/external-radar/summary?limit=15`.
- UI: Самовар → `EXTERNAL RADAR // ВНЕШНИЕ ИСТОЧНИКИ`.
- Связанные механизмы: `GET /api/rag/browse-external`, `POST /api/rag/index-external`,
  `POST /api/filemap/scan`, `GET /api/filemap/candidates`.

## Что читает

Радар не индексирует и не читает содержимое документов. Он объединяет:

- `LES_EXTERNAL_SOURCE_ROOTS`, `LES_EXTERNAL_ALLOW_ANY`, `LES_EXTERNAL_BROWSE_DEFAULT`;
- `data/file_map.db`: `scan_roots`, `file_map`, кандидаты с шифрами;
- MetaDB `documents.source_path`: файлы, уже зарегистрированные через in-place индексацию.

Для корней делается только shallow-статистика непосредственных детей: количество файлов, папок и
поддерживаемых расширений. Глубокий обход остаётся только за явным `POST /api/filemap/scan`.

## Контракт ответа

`/summary` возвращает:

- `roots`: корни с источниками (`configured`, `browse_default`, `filemap`, `indexed_parent`),
  shallow-статистикой, количеством файлов в карте и количеством уже indexed in-place документов;
- `filemap`: число корней карты, файлы с шифрами, топ расширений;
- `candidates`: папки-кандидаты из `file_map_service.suggest_index_candidates()` с абсолютным путём
  и `radar_status= candidate|indexed`;
- `external_documents` и `external_datasets`: текущий объём in-place привязок в MetaDB.

## Границы

- Нет reindex/OCR/LLM.
- Нет полного обхода диска в `/summary`.
- Если карта пуста, радар всё равно показывает configured/browse roots и уже indexed source_path.
- Если документ был зарегистрирован из папки, которой нет в `LES_EXTERNAL_SOURCE_ROOTS` или filemap,
  радар добавляет `indexed_parent` по родителю `source_path`.

## Тесты

- `tests/test_external_radar_service.py` — join filemap + MetaDB source_path, работа без filemap.
- Смежные: `tests/test_external_index.py`, `tests/test_file_map_service.py`.
