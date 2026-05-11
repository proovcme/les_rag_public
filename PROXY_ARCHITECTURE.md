# Proxy Server Architecture

## Overview
The `proxy_server.py` module serves as a proxy server that handles various API requests and manages data processing tasks. It interacts with the backend services, including Qdrant and Ollama, to provide functionalities such as dataset management, file uploads, and chat queries.

## Modules and Dependencies
- **FastAPI**: Used for building the web server.
- **asyncio**: For handling asynchronous operations.
- **psutil**: To gather system metrics.
- **sqlite3**: For database interactions.
- **requests**: For HTTP requests to external services.
- **sse_starlette**: For Server-Sent Events (SSE) support.

## Data Flow
1. **Requests Handling**:
   - Incoming requests are processed by FastAPI endpoints.
   - Requests are validated and routed to appropriate handlers.

2. **Database Interactions**:
   - The server interacts with two SQLite databases: `les_meta.db` and `les_metrics.db`.
   - `les_meta.db` stores metadata about datasets and documents.
   - `les_metrics.db` logs system metrics for monitoring.

3. **Backend Services**:
   - The server communicates with Qdrant for vector storage and retrieval.
   - Ollama is used for language model generation.

4. **Job Tracking**:
   - JobTracker (`job_tracker`) keeps track of ongoing tasks such as dataset synchronization and file uploads.

5. **Server-Sent Events (SSE)**:
   - SSE is used to stream logs and real-time updates to clients.

## SQL Schema
### les_meta.db
- **datasets**: Stores information about datasets.
  - `id`: Dataset ID.
  - `name`: Dataset name.
  - `status`: Status of the dataset.
  - `doc_count`: Number of documents in the dataset.
  - `chunk_count`: Number of chunks in the dataset.

- **documents**: Stores metadata about individual documents.
  - `id`: Document ID.
  - `dataset_id`: Foreign key to datasets.
  - `file_name`: Name of the file.
  - `content`: Content of the document.

### les_metrics.db
- **metrics**: Logs system metrics.
  - `id`: Metric entry ID.
  - `timestamp`: Timestamp of the metric.
  - `cpu`: CPU usage percentage.
  - `ram_used`: Used RAM in GB.
  - `ram_total`: Total RAM in GB.
  - `swap_used`: Used swap space in GB.
  - `disk_used`: Used disk space in GB.
  - `disk_total`: Total disk space in GB.
  - `ollama_ram`: Ollama's RAM usage in GB.
  - `network_ok`: Number of network targets that are reachable.
  - `heartbeat_collector`: Heartbeat timestamp for the metrics collector.
  - `heartbeat_sse`: Heartbeat timestamp for SSE.

## Endpoints
- **/api/health**: Returns the health status of the backend services.
- **/api/metrics**: Provides system and pipeline metrics, including RAG statistics.
- **/api/rag/datasets**: Lists all datasets.
- **/api/rag/datasets/{name}**: Creates a new dataset with the specified name.
- **/api/rag/sources**: Lists all sources and their associated datasets.
- **/api/rag/sync/{folder}**: Synchronizes a folder with a dataset.
- **/api/rag/upload/{dataset_id}**: Uploads a file to a dataset.
- **/api/chat**: Processes chat queries using the RAG model.
- **/api/jobs**: Returns the status of ongoing jobs.
- **/api/logs/stream**: Streams logs in real-time.
- **/**: Serves the frontend HTML page.

## CRAG (Content Retrieval and Generation)
CRAG is responsible for retrieving relevant content from datasets and generating responses using a language model. It involves:
1. Content retrieval from Qdrant based on user queries.
2. Language model generation to produce answers based on retrieved content.
