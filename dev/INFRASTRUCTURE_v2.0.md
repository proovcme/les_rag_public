# 🖥️ Инфраструктура Л.Е.С. v2.0 (Mac Mini M4 + Docker + Ollama)

**Статус:** ✅ Активна | **Обновлено:** 10.05.2026 | **Версия:** 2.0  
**Архитектура:** Headless Mac Mini M4 / 24 GB + ZeroTier P2P + Docker (Qdrant + Proxy) + Ollama Native

## 📋 Узлы сети (ZeroTier)
| Устройство | Роль | IP-адрес | Доступ | ОС |
|---|---|---|---|---|
| Mac Mini M4 | Сервер / Хост | 10.195.146.98 | SSH, Docker, Ollama, UI:8050 | macOS 26.4.1 |
| MacBook Air | Клиент / Управление | 10.195.146.176 | SSH, Browser | macOS |
| Lenovo Legion | Клиент / Управление | 10.195.146.20 | SSH, Browser | Windows 11 |

**Параметры сети:**  
Network ID: `8d1c312afa249de4` | Подсеть: `10.195.146.0/24` | Транспорт: P2P (UDP 9993)

## 🍎 Базовая настройка Mac Mini M4
| Параметр | Команда / Значение | Назначение |
|---|---|---|
| FileVault | Off | Отключено для автономной загрузки |
| Автологин | `sudo defaults write ... autoLoginUser ovc` | Автоматический вход |
| Авторестарт | `sudo pmset -a autorestart 1` | Включение после сбоя питания |
| Сон | `sudo pmset -a sleep 0 disksleep 0` | Запрет спящего режима |
| Сеть | Ethernet (en0) приоритет №1 | Стабильный линк, ZeroTier не мешает |

## 🤖 Ollama Конфигурация (Модельный стек)
**Файл:** `~/.ollama/env`
```env
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=10m
OLLAMA_CONTEXT_LENGTH=8192
```

**Модели:**
| Модель | Размер | Роль | RAM |
|---|---|---|---|
| `qwen3:14b` | 9.3 GB | RAG-чат, Т.О.С.К.А. валидация | ~9.3 GB |
| `qwen2.5-coder:14b` | 9.0 GB | Генерация кода (Roo Code) | ~9.0 GB |
| `bge-m3:latest` | 1.2 GB | Эмбеддинги (векторизация чанков) | ~1.2 GB |

*Ollama автоматически выгружает неактивную модель. Параллельно в RAM живут только чат + эмбеддинг (~10.5 GB).*

## 🐳 Сервисы и контейнеры v2.0
**Путь:** `~/Projects/LES_v2/docker-compose.yml`

| Сервис | Образ | Порт | RAM | Роль |
|---|---|---|---|---|
| `les-qdrant` | `qdrant/qdrant:latest` | 6333 | ~1.5 GB | Векторная БД, хранение чанков и payload |
| `les-proxy` | `python:3.11-slim` (custom) | 8050 | ~0.5 GB | FastAPI ядро, CRAG, ConverterRouter, SSE |

**Зависимости Proxy (`requirements.txt`):**  
FastAPI, Uvicorn, Pydantic v2, LlamaIndex, Qdrant-client, `pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`, `sse-starlette`.

**Хранение данных:**
- `./data/qdrant/` → Volume векторной БД
- `./data/les_meta.db` → SQLite метаданные датасетов/документов
- `./storage/datasets/` → Физические UUID-папки загруженных файлов
- `./RAG_Content/` → Исходники (NTD, BIM, MAIL) для загрузки

## 🔄 Сценарии эксплуатации
### 1. Полный сброс питания
1. Подача 220В → Mac Mini включается (`autorestart 1`).
2. Загрузка macOS → автологин `ovc`.
3. Запуск Login Items → Docker Desktop, Ollama.
4. `docker compose up -d` (если не настроен автозапуск compose).
5. **Итог:** Через 60 сек доступен `http://localhost:8050` и SSH.

### 2. Проверка состояния
```bash
# Статус контейнеров
docker ps --format "table {{.Names}}\t{{.Status}}"

# Память моделей Ollama
ollama ps

# Метрики системы
curl -s http://localhost:8050/api/metrics | python3 -m json.tool
```

### 3. Пересборка ядра (при обновлении кода)
```bash
cd ~/Projects/LES_v2
docker compose build proxy && docker compose up -d proxy
```

## 🛡️ Безопасность
| Уровень | Мера | Статус |
|---|---|---|
| Сеть | ZeroTier P2P, закрытая подсеть | ✅ |
| Доступ | SSH по ключам, UI без пароля (локально) | ✅ |
| Данные | Полностью локально, Zero-Cloud | ✅ |
| Контейнеры | Изоляция сетей Docker, `unless-stopped` | ✅ |
| Модели | Лимиты RAM, автовыгрузка, контекст 8K | ✅ |

## 📝 История изменений
| Дата | Изменение |
|---|---|
| 10.05.2026 | Создана инфраструктура v2.0. Отказ от RAGFlow/ES/MySQL/MinIO. |
| 10.05.2026 | Внедрён стек Qdrant + FastAPI + LlamaIndex + Ollama. |
| 10.05.2026 | Настроен ConverterRouter (pymupdf4llm, mammoth, pandas). |
| 10.05.2026 | Фиксация Ollama env, приоритет Ethernet, структура storage/datasets. |

📅 **Документация актуальна на:** 10.05.2026
