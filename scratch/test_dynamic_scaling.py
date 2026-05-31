import httpx

url = "http://127.0.0.1:8050/api/rag/retrieve-debug"
payload = {
    "question": "Перечень разделов проектной документации по постановлению 87",
    "dataset_filter": "GKRF",
    "top_k": 20
}

r = httpx.post(url, json=payload, timeout=30.0)
print("Status:", r.status_code)
if r.status_code == 200:
    data = r.json()
    chunks = data.get("chunks", [])
    trace = data.get("retrieval_trace", {})
    print(f"Retrieved {len(chunks)} chunks from debug endpoint.")
    print("Merged count in trace:", trace.get("merged_count"))
    print("Quality status:", trace.get("quality", {}).get("status"))
    print("First 20 chunks:")
    for i, c in enumerate(chunks):
        print(f"  [{i+1}] Score: {c.get('score'):.4f} | Snippet: {repr(c.get('preview')[:100])}")
else:
    print(r.text)
