import sqlite3

db_path = "data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT doc_name, chunk_ord, text FROM lexical_chunks WHERE text LIKE 'OFEV%' LIMIT 5")
rows = cur.fetchall()
print("Corrupted/encoded chunks:")
for r in rows:
    print(f"Doc: {r['doc_name']} | Ord: {r['chunk_ord']} | Text: {r['text'][:50]}")

conn.close()
