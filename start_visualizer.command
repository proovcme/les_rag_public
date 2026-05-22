#!/bin/bash
# Л.Е.С. 3D Qdrant Visualizer Launcher

# Change directory to the script's directory
cd "$(dirname "$0")"

echo "========================================================"
echo "      Л.Е.С. 3D Qdrant Database Visualizer Launcher"
echo "========================================================"
echo ""
echo "[*] Working directory: $(pwd)"
echo "[*] Checking if qdrant_visualizer directory exists..."

if [ ! -d "qdrant_visualizer" ]; then
    echo "[-] Error: qdrant_visualizer directory not found!"
    exit 1
fi

echo "[+] Starting lightweight Python HTTP Server on port 8100..."

# Start python server in the background and store PID
python3 -m http.server --directory qdrant_visualizer 8100 &
SERVER_PID=$!

# Wait a second for server to initialize
sleep 1

# Open browser
echo "[+] Opening browser to http://localhost:8100..."
open "http://localhost:8100"

echo ""
echo "[+] Visualizer is running!"
echo "[*] Press Ctrl+C in this terminal window to stop the server."
echo "========================================================"
echo ""

# Handle shutdown
cleanup() {
    echo ""
    echo "[*] Stopping Python HTTP Server (PID: $SERVER_PID)..."
    kill $SERVER_PID
    echo "[+] Done. Goodbye!"
    exit 0
}

trap cleanup INT TERM

# Keep script running to maintain the server
wait $SERVER_PID
