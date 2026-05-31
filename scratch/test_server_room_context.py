import httpx

url = "http://127.0.0.1:8050/api/rag/retrieve-debug"
payload = {
    "question": "Нужно ли тушить серверную газом и от какой площади?",
    "dataset_filter": "NTD_FIRE"
}

r = httpx.post(url, json=payload, timeout=30.0)
print("Status:", r.status_code)
if r.status_code == 200:
    data = r.json()
    chunks = data.get("chunks", [])
    if chunks:
        c1 = chunks[0]
        print("=== Top Chunk doc_name ===")
        print(c1.get("doc_name"))
        print("\n=== Expanded Context Window ===")
        print(c1.get("expanded_preview"))
    else:
        print("No chunks retrieved!")
else:
    print(r.text)
