import sqlite3

db_path = "data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

doc_name = "GKRF/Постановление Правительства РФ от 16.02.2008 N 87 (ред. от 09.04.2021).pdf"

# Count total chunks for PP 87 PDF
cur.execute("SELECT count(*) as cnt FROM lexical_chunks WHERE doc_name = ?", (doc_name,))
cnt = cur.fetchone()['cnt']
print(f"Total chunks for '{doc_name}': {cnt}")

# Let's list some chunks and see their ordering
cur.execute("SELECT chunk_ord, text FROM lexical_chunks WHERE doc_name = ? ORDER BY chunk_ord LIMIT 30", (doc_name,))
chunks = cur.fetchall()
print("\nFirst 30 chunks:")
for c in chunks:
    text_preview = c['text'].replace('\n', ' ')[:100]
    print(f"  Ord {c['chunk_ord']}: {text_preview}")

# Check if there are any chunks with real Russian text
cur.execute("SELECT chunk_ord, text FROM lexical_chunks WHERE doc_name = ? AND text NOT LIKE 'OFE%' AND text NOT LIKE 'Bsz%' LIMIT 10", (doc_name,))
real_chunks = cur.fetchall()
print(f"\nReal chunks for '{doc_name}':")
for c in real_chunks:
    text_preview = c['text'].replace('\n', ' ')[:100]
    print(f"  Ord {c['chunk_ord']}: {text_preview}")

conn.close()
