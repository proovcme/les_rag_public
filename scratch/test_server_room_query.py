import httpx

url = "http://127.0.0.1:8050/api/chat"
payload = {
    "question": "Нужно ли тушить серверную газом и от какой площади?",
    "dataset_filter": "NTD_FIRE",
    "semantic_cache_enabled": False
}

print("Sending server room chat request...")
r = httpx.post(url, json=payload, timeout=300.0)
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
