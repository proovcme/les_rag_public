import sqlite3

db_path = "/Users/ovc/Projects/LES_v2/data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT chunk_ord, text FROM lexical_chunks WHERE doc_name LIKE '%486%' AND (text LIKE '%сервер%' OR text LIKE '%связи%' OR text LIKE '%вычислител%')")
rows = cur.fetchall()
print(f"Found {len(rows)} matching chunks in СП 486:")
for r in rows:
    print(f"\n--- Chunk Ord: {r[0]} ---")
    print(r[1][:500])

conn.close()
