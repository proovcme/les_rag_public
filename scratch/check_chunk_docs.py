import sqlite3

db_path = "/Users/ovc/Projects/LES_v2/data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT doc_name, dataset_id, chunk_ord FROM lexical_chunks WHERE doc_name LIKE '%486%' AND chunk_ord IN (59, 60)")
for r in cur.fetchall():
    print(f"Doc: {r[0]} | Dataset ID: {r[1]} | Ord: {r[2]}")

conn.close()
