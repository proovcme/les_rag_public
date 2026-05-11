# LES Infrastructure v2.0

## Overview
The LES infrastructure consists of several components that work together to provide a robust and scalable system for dataset management, file uploads, and chat queries.

## Components
- **Proxy Server**: `proxy_server.py` - Handles API requests and manages data processing tasks.
- **Backend Services**:
  - Qdrant: Vector storage and retrieval.
  - Ollama: Language model generation.
- **Databases**:
  - `les_meta.db`: Stores metadata about datasets and documents.
  - `les_metrics.db`: Logs system metrics for monitoring.

## Recent Updates
### v2.0.1
- **RAG Metrics Integration**: Added RAG statistics to `/api/metrics` endpoint.
  - Datasets: 4
  - Files: 809
  - Chunks: 1316
  - Status: Ready

## Known Issues
- None at the moment.

## Future Work
- Continue improving performance and stability.
- Expand functionality to support additional data formats and models.
