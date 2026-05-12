#!/bin/bash
# =============================================================================
# mode_code.sh — Переключение в режим КОД
# Останавливает RAG-модель, загружает qwen2.5-coder:32b
# Запуск: bash ~/Projects/LES_v2/mode_code.sh
# =============================================================================

OLLAMA="ollama"
RAG_MODEL="qwen3:14b"
CODE_MODEL="qwen2.5-coder:32b"
API="http://localhost:8050/api/mode"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}[КОД] Переключение режима...${NC}"

# Выгружаем RAG-модель
echo -e "${YELLOW}[1/3] Выгружаем ${RAG_MODEL}...${NC}"
$OLLAMA stop "$RAG_MODEL" 2>/dev/null || true

# Проверяем что модель есть локально
if ! $OLLAMA list | grep -q "$CODE_MODEL"; then
    echo -e "${YELLOW}[!] ${CODE_MODEL} не найдена локально. Скачиваем...${NC}"
    $OLLAMA pull "$CODE_MODEL"
fi

# Прогреваем кодовую модель
echo -e "${YELLOW}[2/3] Загружаем ${CODE_MODEL}...${NC}"
$OLLAMA run "$CODE_MODEL" --keepalive 60m "" 2>/dev/null &
sleep 5

# Сообщаем прокси о смене режима (если endpoint есть)
echo -e "${YELLOW}[3/3] Уведомляем Л.Е.С....${NC}"
curl -s -X POST "$API" \
  -H "Content-Type: application/json" \
  -d "{\"mode\": \"code\", \"model\": \"$CODE_MODEL\"}" 2>/dev/null || true

# Показываем что в памяти
echo ""
echo -e "${GREEN}[OK] Режим КОД активен${NC}"
echo ""
$OLLAMA ps
echo ""
echo -e "${CYAN}Модель:   ${CODE_MODEL}${NC}"
echo -e "${CYAN}Roo Code: http://localhost:11434/v1${NC}"
echo -e "${CYAN}Вернуться в RAG: bash ~/Projects/LES_v2/mode_rag.sh${NC}"
