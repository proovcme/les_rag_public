import httpx

url = "http://127.0.0.1:8050/api/chat"
payload = {
    "question": "Перечень разделов проектной документации по постановлению 87",
    "dataset_filter": "GKRF",
    "semantic_cache_enabled": False
}

print("Sending chat request (this may take a few seconds as Qwen generates the answer)...")
r = httpx.post(url, json=payload, timeout=180.0)
print("Status:", r.status_code)
if r.status_code == 200:
    data = r.json()
    print("\n--- Answer ---")
    print(data.get("answer"))
    print("\n--- CRAG Status ---")
    print(data.get("crag_status"))
    print("\n--- Sources ---")
    print(data.get("sources"))
else:
    print(r.text)
