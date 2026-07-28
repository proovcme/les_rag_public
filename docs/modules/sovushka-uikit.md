# Sovushka P0 UI kit

## Назначение

`sovushka/uikit/` — минимальный общий слой для критического пути `/classic`:
токены, доступные состояния и устойчивые CSS-классы компонентов. Он не
переписывает все исторические экраны и не меняет продуктовую логику.

## Контракт P0

- `tokens.py` задаёт типографику, размеры, радиусы, focus, reduced motion,
  тени и адаптацию на мобильной ширине.
- `components.py` даёт `StatusBadge` и общий рендер `Loading`, `Empty`,
  `Error`, `Blocked`.
- `states.py` хранит проверяемые человеческие тексты состояний.
- `sovushka_ng._apply_theme()` подключает UI kit после текущей темы, поэтому
  мигрированные классы имеют один приоритет, а остальные экраны остаются
  совместимыми.

Мигрированные поверхности: AppShell/Header, чат, evidence/source cards и
`build_documents(surface=...)`. В payload чата `BLOCKED` выводится отдельно
от ответа модели; машинный `error_code` и действие остаются видимыми, а
технический trace свёрнут.

## Границы

- Не добавляет JavaScript/CSS-зависимости.
- Не скрывает `MISSING/BLOCKED` и не создаёт источники.
- Не меняет RAG, выбор модели или права API.
- Полная замена исторического `sovushka/styles.py` не входит в P0.

## Проверка

```bash
uv run pytest -q tests/test_sovushka_uikit.py tests/test_static_assets.py \
  tests/test_sovushka_chat.py tests/test_sovushka_trust.py
```

Живой выпуск дополнительно проверяет `/ → /classic`, `/les/classic`,
desktop/mobile viewport, горизонтальный overflow и видимый focus.
