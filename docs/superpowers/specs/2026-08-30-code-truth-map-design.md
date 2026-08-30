# 0.30.5 — удаление доказанного исторического хвоста

Статус: граница утверждена владельцем 2026-08-30.

## Цель

Удалить первую безопасную группу файлов, которые не имеют пути от боевых entrypoint
ЛЕС и не являются сохраняемой продуктовой функцией. Это уборка, а не изменение продукта.

## Удаляемая группа

- `backend/auth_login_route.py` — старый HTML login route; живой login регистрирует
  `sovushka.auth`;
- `backend/login.html` — шаблон, который использовался только старым login route;
- `backend/diagnostics.py` — сам помечен как мёртвый; живая диагностика находится в
  `proxy/routers/diagnostics.py` и `sovushka/pages/diag.py`;
- `backend/inference/sparse_embed.py` — оставленный эксперимент BGE-M3 learned-sparse;
  production contract использует `bm25_sparse`;
- пустые `proxy/{clients,repositories,workers}/__init__.py` и ставшие пустыми каталоги;
- `qdrant_visualizer/export_data.py` — неиспользуемый standalone exporter старого
  vector contract; сам активный визуализатор остаётся;
- `sovushka/components/logterm.py` — отключённый terminal footer;
- `sovushka/pages/{overview,prorab,obyomy,zadachi,mermaid_page,rim}.py` — не подключённые
  страницы. Отдельный RIM UI признан ошибкой; живой RIM backend/API и универсальный
  агент остаются.

## Не трогаем

- `sovushka/pages/mail.py`: Mail UI будет возвращён после отдельной переработки;
- `proxy/legacy_app.py`: внешний compatibility shim требует отдельного решения;
- старый scenario/deterministic harness — отдельная следующая группа;
- `proxy/smeta_core/**`, RIM services/router/session и сметные алгоритмы;
- RAG, модели, updater, пользовательские данные и установленный runtime;
- активные файлы Qdrant visualizer.

## Метод

Удаление выполняется независимыми группами: backend-хвост, пустые packages,
standalone/UI infrastructure, затем не подключённые страницы. Перед каждой группой
проверяется отсутствие product-imports; после — точечные тесты и пересборка generated
runtime map. Тесты больше не должны требовать физического сохранения dormant UI; они
продолжают защищать production shell от скрытого подключения удалённых поверхностей.

Канонические документы исправляются только там, где они называют удаляемый файл
активной точкой входа. Новая продуктовая архитектура не проектируется.

## Приёмка

- удаляемые пути отсутствуют под git;
- `sovushka/pages/mail.py`, `proxy/legacy_app.py` и `proxy/smeta_core/**` не изменены;
- generated map не содержит удалённых путей и остаётся детерминированной;
- production entrypoints импортируются из staged Windows runtime;
- `make verify`, `make test` и `make test-tauri` зелёные;
- сметный benchmark не требуется, потому что защищённый код не меняется;
- deploy, publish и live runtime update не выполняются.

## Откат

Каждая группа удаляется отдельным коммитом или остаётся отдельным логическим diff.
При провале возвращается только соответствующая группа через git; данные и runtime
не затрагиваются.
