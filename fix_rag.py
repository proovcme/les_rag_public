import re
from pathlib import Path

filepath = Path("proxy_server.py")
lines = filepath.read_text().splitlines(keepends=True)

# Найди функцию get_metrics
start = None
for i, line in enumerate(lines):
    if line.lstrip().startswith("async def get_metrics():"):
        start = i
        break
if start is None:
    print("ERR:FUNC_NOT_FOUND")
    exit(1)

# Найди return { внутри функции
ret_idx = None
for i in range(start, min(start+30, len(lines))):
    if lines[i].strip() == "return {":
        ret_idx = i
        break
if ret_idx is None:
    print("ERR:RETURN_NOT_FOUND")
    exit(1)

# Определи отступ return {
indent = len(lines[ret_idx]) - len(lines[ret_idx].lstrip())
bi = " " * (indent + 4)

# Собери блок rag_stats с правильными отступами
rb = []
rb.append(f"{bi}rag_stats = {{\"datasets\": 0, \"files\": 0, \"chunks\": 0, \"status\": \"unknown\"}}\n")
rb.append(f"{bi}try:\n")
rb.append(f"{bi}    _c = sqlite3.connect(DB_PATH)\n")
rb.append(f"{bi}    _c.execute(\"SELECT COUNT(*) FROM datasets\")\n")
rb.append(f"{bi}    rag_stats[\"datasets\"] = _c.fetchone()[0] or 0\n")
rb.append(f"{bi}    _c.execute(\"SELECT COUNT(*) FROM documents\")\n")
rb.append(f"{bi}    rag_stats[\"files\"] = _c.fetchone()[0] or 0\n")
rb.append(f"{bi}    _c.close()\n")
rb.append(f"{bi}    if qdrant_client:\n")
rb.append(f"{bi}        coll = qdrant_client.get_collection(\"les_rag\")\n")
rb.append(f"{bi}        rag_stats[\"chunks\"] = coll.points_count or 0\n")
rb.append(f"{bi}        rag_stats[\"status\"] = \"ready\" if rag_stats[\"chunks\"] > 0 else \"indexing\"\n")
rb.append(f"{bi}except Exception as e:\n")
rb.append(f"{bi}    logger.warning(f\"RAG stats error: {{e}}\")\n")
rb.append(f"{bi}    rag_stats[\"status\"] = \"error\"\n")
rb.append("\n")

# Вставь блок перед return {
lines[ret_idx:ret_idx] = rb

# Найди "heartbeats" и добавь запятую + rag
for i in range(ret_idx+1, min(ret_idx+50, len(lines))):
    if '"heartbeats": heartbeats' in lines[i]:
        lines[i] = lines[i].rstrip().rstrip(",") + ",\n"
        lines.insert(i+1, f'{bi}"rag": rag_stats\n')
        break

filepath.write_text("".join(lines))
print("PATCH_OK")
