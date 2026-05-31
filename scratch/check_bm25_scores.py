import sqlite3
from proxy.services.lexical_index_service import LexicalIndex, build_fts_query
from proxy.services.retrieval_service import expand_retrieval_query

db_path = "/Users/ovc/Projects/LES_v2/data/les_meta_qwen.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

question = "Нужно ли тушить серверную газом и от какой площади?"
expanded = expand_retrieval_query(question)
fts_query = build_fts_query(expanded)

print("Expanded Query:", repr(expanded))
print("FTS Query:", repr(fts_query))

# Query matching chunks in NTD_FIRE_Index (dataset_id: d69171e9-2fda-4d8a-bfd5-ed2fd97aa630)
sql = """
    SELECT c.chunk_ord, c.text, bm25(lexical_chunks_fts) as score
    FROM lexical_chunks_fts
    JOIN lexical_chunks c ON c.id = lexical_chunks_fts.rowid
    WHERE lexical_chunks_fts MATCH ? AND c.collection="les_rag_qwen3_06b" AND c.dataset_id="d69171e9-2fda-4d8a-bfd5-ed2fd97aa630"
    ORDER BY score ASC LIMIT 30
"""
cur.execute(sql, (fts_query,))
rows = cur.fetchall()

print(f"\nTop 30 FTS matching chunks in NTD_FIRE_Index:")
for i, r in enumerate(rows):
    print(f"[{i+1}] Ord: {r['chunk_ord']} | BM25 Score: {r['score']:.4f} | Snippet: {repr(r['text'][:200])}")

conn.close()
