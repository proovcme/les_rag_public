import sqlite3

db_path = "data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Total chunks
cur.execute("SELECT count(*) as cnt FROM lexical_chunks")
total_chunks = cur.fetchone()['cnt']
print(f"Total chunks in database: {total_chunks}")

# 2. Total chunks with null chunk_ord
cur.execute("SELECT count(*) as cnt FROM lexical_chunks WHERE chunk_ord IS NULL")
null_ord_chunks = cur.fetchone()['cnt']
print(f"Chunks with chunk_ord IS NULL: {null_ord_chunks}")

# 3. Documents with null chunk_ord chunks
cur.execute("SELECT DISTINCT doc_name FROM lexical_chunks WHERE chunk_ord IS NULL LIMIT 20")
null_docs = cur.fetchall()
print("\nDocuments with null chunk_ord chunks:")
for d in null_docs:
    print(f"- {d['doc_name']}")

# 4. Check text length and type of those null chunks
cur.execute("SELECT doc_name, length(text) as len, text FROM lexical_chunks WHERE chunk_ord IS NULL LIMIT 5")
null_samples = cur.fetchall()
print("\nSamples of null chunk_ord chunks:")
for s in null_samples:
    print(f"- Doc: {s['doc_name']} | Length: {s['len']} | Text: {repr(s['text'][:100])}")

# 5. Let's see how many documents are indexed in total
cur.execute("SELECT count(DISTINCT doc_name) as cnt FROM lexical_chunks")
total_docs = cur.fetchone()['cnt']
print(f"\nTotal unique documents in database: {total_docs}")

conn.close()
