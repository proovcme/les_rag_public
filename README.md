# 🌲 Л.Е.С. — Локальная Экспертная Система

**Локальная RAG-система для работы с нормативной документацией.**  
Работает полностью офлайн на Apple Silicon (Mac Mini M4). Никакие данные не покидают локальную сеть.

---

## Что это

Л.Е.С. — это система для поиска и анализа технических норм, СП, ГОСТ, проектной документации. Задаёшь вопрос на русском языке — получаешь ответ со ссылками на источники и оценкой достоверности.

```
Вопрос: "Минимальная ширина пути эвакуации по СП 1.13130?"
Ответ:  "Не менее 1,2 м (п. 4.3.4 СП 1.13130.2022). [VERIFIED]"
         └── Источник: СП 1.13130.2022.pdf, стр. 12
```

---

## Архитектура

```
┌─────────────────────────────────────────────────┐
│              Mac Mini M4 / 24 GB                │
│                                                 │
│  С.О.В.У.Ш.К.А.  (NiceGUI UI, порт 8051)       │
│       │                                         │
│  les-proxy  (FastAPI, порт 8050)                │
│       ├── RAG pipeline                          │
│       ├── Т.О.С.К.А. (CRAG валидация)           │
│       └── В.О.Л.К.   (auth, ключи доступа)      │
│       │                                         │
│  MLX Native Host  (порт 8080)                   │
│       ├── Qwen3-14B-4bit  (LLM, Metal)          │
│       ├── Qwen3-4B-4bit   (валидатор)           │
│       └── BGE-M3          (эмбеддинги, MPS)     │
│       │                                         │
│  Qdrant  (векторная база, порт 6333)            │
└─────────────────────────────────────────────────┘
         │  ZeroTier overlay network
┌────────┴────────────────────────────────────────┐
│  VPS П.А.У.К. (Debian 13)                       │
│  Caddy → HTTPS les.ovc.me → Mac Mini           │
└─────────────────────────────────────────────────┘
```

---

## Модули системы

| Аббревиатура | Расшифровка | Роль |
|---|---|---|
| **С.О.В.У.Ш.К.А.** | Система Оперативного Взаимодействия с Умной Шкатулкой Корпоративных Активов | UI (NiceGUI) |
| **С.А.М.О.В.А.Р.** | Система Автоматической Масштабируемой Обработки Векторных Архивов Регламентов | RAG / Qdrant |
| **Т.О.С.К.А.** | Технология Оценки Соответствия Контента Архивным данным | CRAG валидатор |
| **В.О.Л.К.** | Валидатор Ограничений Лиц и Ключей | Auth / RBAC |
| **П.А.У.К.** | Периметральный Аванпост Удалённого Контроля | VPS прокси |
| **Е.Ж.И.К.** | Ежедневный Журнализатор Инженерной Корреспонденции | IMAP / почта |
| **Ж.А.Б.А.** | — | Mac Mini (хост) |

---

## Стек

| Компонент | Технология |
|---|---|
| LLM | [Qwen3-14B-4bit](https://huggingface.co/mlx-community/Qwen3-14B-4bit) via MLX |
| Валидатор | Qwen3-4B-4bit (CRAG: VERIFIED / NO_DATA / HALLUCINATION) |
| Эмбеддинги | [BGE-M3](https://huggingface.co/BAAI/bge-m3) via sentence-transformers + MPS |
| Векторная база | [Qdrant](https://qdrant.tech/) |
| Backend | FastAPI + httpx |
| Frontend | [NiceGUI](https://nicegui.io/) |
| Внешний доступ | Caddy + Let's Encrypt + ZeroTier |
| Форматы документов | PDF, DOCX, XLSX, CSV, EML, MSG, JSON, MD, TXT |

---

## Быстрый старт

### Требования
- Mac с Apple Silicon (M1/M2/M4) и минимум 16 GB RAM
- Docker Desktop
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Python 3.11+

### Установка

```bash
git clone https://github.com/yourname/les-rag-public
cd les-rag-public

# Зависимости
uv sync

# Конфигурация
cp .env.example .env
# Отредактируй .env — укажи модели и пароль

# Запуск
docker compose up -d          # Qdrant
./start_mlx.command           # MLX Host (LLM + Embeddings)
uv run python3 sovushka_ng.py # UI
```

Открой `http://localhost:8051`

### Добавление документов

```bash
# Положи PDF/DOCX в папку
mkdir -p RAG_Content/MyDocs
cp my_norms/*.pdf RAG_Content/MyDocs/

# Запусти индексацию через UI или curl
curl -X POST http://localhost:8050/api/rag/sync/MyDocs
```

---

## RAG Pipeline

```
Запрос пользователя
      │
      ▼
Векторный поиск (BGE-M3 + Qdrant)
      │  top-5 чанков
      ▼
Промпт = системный + контекст + вопрос
      │
      ▼
Qwen3-14B (MLX, Metal)
      │  ответ
      ▼
Т.О.С.К.А. валидация (Qwen3-4B)
      │  VERIFIED / NO_DATA / HALLUCINATION
      ▼
Ответ пользователю + источники
```

---

## Форматы вывода

С.О.В.У.Ш.К.А. умеет форматировать ответ в:
- Свободный текст
- Спецификацию оборудования (по ГОСТ 21.110)
- JSON-дерево / иерархическую схему
- Mermaid-диаграмму (flowchart, sequence, ER)
- SVG-схему
- Произвольную таблицу

---

## Внешний доступ (П.А.У.К.)

Система доступна через HTTPS без открытия портов домашней сети:

```
Интернет → les.ovc.me (VPS, Caddy, SSL)
                │
          ZeroTier VPN
                │
         Mac Mini :8050/:8051
```

Доступ по ключам (В.О.Л.К.):
- `admin` — полный интерфейс
- `user`  — только AI ЧАТ

---

## Структура репозитория (публичная версия)

```
les-rag-public/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Dockerfile.proxy
├── start_mlx.command
├── stop_mlx.command
├── mlx_host.py              ← MLX Native Host
├── backend/
│   ├── mlx_adapter.py       ← MLXMemoryManager
│   ├── qdrant_adapter.py    ← EmbedClient + RAG
│   ├── converter.py         ← PDF/DOCX/XLSX → текст
│   ├── metrics_collector.py
│   └── interface.py
├── sovushka/                ← UI модули (рефакторинг)
│   ├── auth.py              ← В.О.Л.К.
│   ├── state.py
│   ├── styles.py
│   └── pages/
│       ├── chat.py
│       ├── samovar.py
│       └── ...
└── sovushka_ng.py           ← точка входа UI
```

**Не входит в публичную версию:** `proxy_server.py` (содержит внутреннюю логику), `.env`, ключи, данные индексов.

---

## Лицензия

MIT — используй, форкай, улучшай.  
Если делаешь что-то интересное на этой базе — открой issue, интересно посмотреть.

---

## Дорожная карта

- [x] RAG pipeline (Qdrant + BGE-M3 + Qwen3)
- [x] CRAG валидация (Т.О.С.К.А.)
- [x] NiceGUI интерфейс (С.О.В.У.Ш.К.А.)
- [x] Внешний доступ через VPS (П.А.У.К.)
- [x] Auth по ключам (В.О.Л.К.)
- [ ] Е.Ж.И.К. — IMAP коннектор для почты
- [ ] VLM pipeline — анализ PDF-чертежей через Gemma 4
- [ ] Folder Watcher — автосинк новых файлов
- [ ] Parquet pipeline для смет и спецификаций
