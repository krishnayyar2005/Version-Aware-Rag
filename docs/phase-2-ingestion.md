# Phase 2: Document Chunking & Embedding Ingestion Pipeline

## 1. Markdown-Aware Chunking Strategy
- **Parser**: Hierarchy-preserving block parser that tracks heading paths (e.g. `Policy > Section > Subsection`) and binds headings to subsequent paragraph content.
- **Chunk Sizing Parameters**:
  - Target chunk size: ~200 words (`TARGET_WORDS = 200`).
  - Maximum chunk size hard cap: 300 words (`MAX_WORDS = 300`), splitting over-length sections on sentence boundaries.
  - Minimum chunk size at headings: 50 words (`MIN_WORDS = 50`) before triggering a boundary break.
- **Normalized Schema**: Chunks reference `version_id` rather than duplicating document metadata, allowing updates to version validity without touching individual chunks.

## 2. Embedding Model & Ingestion Architecture
- **Model**: `BAAI/bge-small-en-v1.5` producing 384-dimensional dense vectors (matching PostgreSQL `vector(384)`).
- **Engine**: Local embedding generation via `fastembed` (ONNX Runtime-backed, running locally without external API latency or rate limits).
- **Resumability**: The ingestion script processes versions that have zero chunks in the database (`WHERE NOT EXISTS (SELECT 1 FROM chunks ...)`), making the process fully idempotent and safe to resume across interruptions.

## 3. Results & Ingestion Metrics
- **Total Chunks Created**: 10,054 chunks across 324 versions.
- **Embedding Coverage**: 100% (10,054 / 10,054 chunks embedded).
- **Average Word Count**: ~153 words per chunk (max 300 words).
- **Database Footprint**: 70 MB database size in Supabase PostgreSQL with `pgvector` index and full-text search vectors.
- **Total Ingestion Runtime**: ~16 minutes for the full corpus.
