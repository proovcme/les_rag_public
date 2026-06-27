#!/bin/bash
# =============================================================================
# mode_rag.sh — Переключение в режим РАГ
# Останавливает кодовую модель, загружает qwen3:14b + bge-m3
# Запуск: bash ~/Projects/LES_v2/mode_rag.sh
# =============================================================================

OLLAMA="ollama"
CODE_MODEL="qwen2.5-coder:32b"
RAG_MODEL="qwen3:14b"
EMBED_MODEL="bge-m3:latest"
API="http://localhost:8050/api/mode"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}[РАГ] Переключение режима...${NC}"

# Выгружаем кодовую модель
echo -e "${YELLOW}[1/3] Выгружаем ${CODE_MODEL}...${NC}"
$OLLAMA stop "$CODE_MODEL" 2>/dev/null || true

# Прогреваем RAG-модель
echo -e "${YELLOW}[2/3] Загружаем ${RAG_MODEL}...${NC}"
$OLLAMA run "$RAG_MODEL" --keepalive 60m "" 2>/dev/null &
sleep 5

# Прогреваем эмбеддинг (он маленький, грузится быстро)
echo -e "${YELLOW}[2/3] Загружаем ${EMBED_MODEL}...${NC}"
curl -s http://localhost:11434/api/embeddings \
  -d "{\"model\": \"$EMBED_MODEL\", \"prompt\": \"warmup\"}" > /dev/null 2>&1 || true

# Уведомляем прокси
echo -e "${YELLOW}[3/3] Уведомляем Л.Е.С....${NC}"
curl -s -X POST "$API" \
  -H "Content-Type: application/json" \
  -d "{\"mode\": \"rag\", \"model\": \"$RAG_MODEL\"}" 2>/dev/null || true

# Показываем что в памяти
echo ""
echo -e "${GREEN}[OK] Режим РАГ активен${NC}"
echo ""
$OLLAMA ps
echo ""
echo -e "${CYAN}Модель:   ${RAG_MODEL} + ${EMBED_MODEL}${NC}"
echo -e "${CYAN}UI:       http://localhost:8050${NC}"
echo -e "${CYAN}Вернуться в КОД: bash ~/Projects/LES_v2/mode_code.sh${NC}"
