#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import os
import sys
from datetime import datetime

# Configure host
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
DEFAULT_COLLECTION = "les_rag"

print("========================================================")
print("      Qdrant Standalone Data Exporter for 3D Visualizer")
print("========================================================")

# 1. Fetch available collections
print(f"[*] Querying Qdrant collections at {QDRANT_URL}...")
try:
    req = urllib.request.Request(f"{QDRANT_URL}/collections", method="GET")
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())
        collections = [c["name"] for c in data["result"]["collections"]]
except Exception as e:
    print(f"[-] Error connecting to Qdrant: {e}")
    print("[-] Please ensure Qdrant is running and accessible.")
    sys.exit(1)

if not collections:
    print("[-] No collections found in Qdrant database.")
    sys.exit(1)

print(f"[+] Found collections: {', '.join(collections)}")

# Select collection
collection_name = DEFAULT_COLLECTION
if collection_name not in collections:
    collection_name = collections[0]

print(f"[*] Selected collection to export: '{collection_name}'")

# 2. Fetch all points with vectors and payloads
print(f"[*] Fetching points (vectors + payload) from '{collection_name}'...")

scroll_payload = {
    "limit": 1500,
    "with_vector": True,
    "with_payload": True
}

req_data = json.dumps(scroll_payload).encode('utf-8')
headers = {'Content-Type': 'application/json'}

try:
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{collection_name}/points/scroll",
        data=req_data,
        headers=headers,
        method="POST"
    )
    with urllib.request.urlopen(req) as res:
        response_data = json.loads(res.read().decode())
        points = response_data["result"]["points"]
except Exception as e:
    print(f"[-] Error fetching points: {e}")
    sys.exit(1)

if not points:
    print("[-] No points found in this collection.")
    sys.exit(1)

total_points = len(points)
vector_dim = len(points[0]["vector"]) if total_points > 0 else 0
print(f"[+] Successfully fetched {total_points} points with {vector_dim}-dimensional vectors!")

# 3. Save as data.js
script_dir = os.path.dirname(os.path.abspath(__file__))
output_file = os.path.join(script_dir, "data.js")

export_structure = {
    "collectionName": collection_name,
    "exportDate": datetime.now().isoformat(),
    "points": points
}

print(f"[*] Writing standalone data to {output_file}...")

try:
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("// Standalone backup data for 3D Visualizer\n")
        f.write(f"// Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("export const qdrantBackupData = ")
        json.dump(export_structure, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    
    print("[+] Export completed successfully!", "highlight")
    print(f"[+] File size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")
    print("[*] Now the visualizer can run completely offline without Qdrant running!")
    print("========================================================")

except Exception as e:
    print(f"[-] Error writing file: {e}")
    sys.exit(1)
