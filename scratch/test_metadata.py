import httpx

url = "http://127.0.0.1:8050/api/rag/retrieve-debug"
payload = {
    "question": "Нужно ли тушить серверную газом и от какой площади?",
    "dataset_filter": "NTD_FIRE"
}

r = httpx.post(url, json=payload, timeout=30.0)
if r.status_code == 200:
    data = r.json()
    chunks = data.get("chunks", [])
    if chunks:
        c1 = chunks[0]
        print("=== Chunk Keys ===")
        print(c1.keys())
        print("\n=== Chunk Meta ===")
        print(c1.get("meta"))
    else:
        print("No chunks!")
else:
    print(r.text)
