# LES Proxy v2.0

## Overview
The LES Proxy is a web server that acts as a proxy for various backend services, including dataset management, file uploads, and chat queries. It provides an API interface for interacting with these services.

## Features
- **Dataset Management**: Create, list, and manage datasets.
- **File Uploads**: Upload files to datasets and trigger parsing tasks.
- **Chat Queries**: Process chat queries using the RAG (Retrieval-Augmented Generation) model.
- **Metrics**: Monitor system and pipeline metrics through `/api/metrics`.

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
