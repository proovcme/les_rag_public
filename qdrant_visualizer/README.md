# 3D Qdrant Vector Space Visualizer

A stunning, immersive 3D scatter plot visualizer for Qdrant database vector embeddings. Designed to operate completely client-side in your browser, it utilizes high-performance **Three.js** instancing and a customized **Principal Component Analysis (PCA)** algorithm to project 1024-dimensional embeddings into a beautiful 3D knowledge constellation.

---

## 🚀 Key Features

*   **Interactive 3D Navigation**: Orbit, pan, and zoom smoothly through your collection.
*   **High Performance**: Uses `THREE.InstancedMesh` to render hundreds or thousands of nodes smoothly at 60 FPS.
*   **Client-Side PCA**: Dynamically computes means, covariance matrix, and eigenvalues to project high-dimensional embeddings on-the-fly.
*   **Constellation Mode**: Automatically calculates and draws glowing neon semantic connection links between nearest neighbor vector pairs.
*   **Live Search**: Realtime payload text querying dynamically highlights matching vectors and dims non-matching coordinates.
*   **Document Isolation**: Isolate and toggle visibility of individual source files (`.docx`, `.pdf`, etc.) to analyze their structural distribution.
*   **Deep Inspection Panel**: Click any node to open a glassmorphic sidebar showing full vector details: Point UUID, file metadata, 3D PCA coordinates, and raw payload text chunks.

---

## 🛠️ How to Launch

Because browsers block local ES module imports (`file://`) due to CORS security rules, this application must be served over a local HTTP port.

### Method 1: Double-click (macOS)
Double-click the **`start_visualizer.command`** script located in the main directory. This automatically launches a tiny, zero-dependency Python server on port `8100` and opens the application in your default web browser.

### Method 2: Manual Terminal
1. Open a terminal in this directory.
2. Run a simple Python server:
   ```bash
   python3 -m http.server 8100
   ```
3. Open your browser and navigate to:
   [http://localhost:8100](http://localhost:8100)

---

## 🕹️ Controls Guide

*   **Rotate Orbit**: `Left Click` + `Drag`
*   **Zoom In/Out**: `Scroll Wheel`
*   **Pan Camera**: `Right Click` / `Ctrl + Click` + `Drag`
*   **Select Point**: `Left Click` on any sphere node
*   **Deselect / Close Sidebar**: Click `×` in the top right of the Inspection Panel
