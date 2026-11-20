# Phase 1: Data Acquisition, Synthetic Ground Truth & Database Schema

## 1. Real Document Dataset (Open Terms Archive)
- **Source**: Open Terms Archive `contrib` dataset.
- **License**: Open Database License (ODbL) by Open Terms Archive contributors.
- **Selection Rules**:
  - Minimum 3 versions per document (`MIN_VERSIONS = 3`).
  - Span of at least 180 days between earliest and latest versions (`MIN_SPAN_DAYS = 180`).
  - Minimum 2,000 characters per version (`MIN_CHARS = 2000`) to filter out placeholders or broken scrapes.
  - Maximum 6 versions per document (`MAX_VERSIONS = 6`), evenly spaced across time while retaining the earliest and latest versions.
  - Maximum 2 document types per service.
- **Yield**: 40 real documents across diverse services with 240 total historical versions.

## 2. Synthetic Dataset & Planted Contradictions
- **Companies**: 7 synthetic companies (Northwind Labs, Brightpath Logistics, Crestline Financial, Helios Renewables, Maple & Finch Retail, Orbital Health, Tidewater Foods).
- **Documents & Versions**: 31 documents with 84 total versions covering Leave, Travel & Expense, IT Security & Remote Work policies, and corresponding FAQs.
- **Planted Contradictions & Controls**:
  - **7 Planted Stale-FAQ Conflicts**: Current FAQs that still quote superseded policy terms, producing explicit cross-document contradictions between two documents marked `current`.
  - **43 Consistent-FAQ Controls**: Negative controls where current FAQs correctly align with active policy terms (ensuring conflict detection avoids false positives).
  - **108 Evaluation Questions**: Structured query benchmarks with expected ground-truth answers and target versions for both `current` and point-in-time (`as_of`) evaluation modes.

## 3. Database Schema (Supabase PostgreSQL + pgvector)
The database schema separates document tracking, version histories, and vector chunks to ensure metadata lives in a single place:
- **`documents`**: Document identity, family, source URL, and synthetic flag.
- **`doc_versions`**: Version labels (`v1`, `v2`, ...), effective dates, expiry dates, status (`current` vs. `superseded`), supersedes references, and raw markdown text. Exactly one version is marked `current` per document.
- **`chunks`**: Content chunks linked to `doc_versions` via `version_id`, with section paths, full-text search vectors (`tsv`), and dense 384-dimensional vector embeddings (`vector(384)`).
- **`conflicts`**: Table for detected or planted factual contradictions between document versions.

**Summary of Loaded Records**:
- **71 documents** (40 real + 31 synthetic).
- **324 versions** (240 real + 84 synthetic).
- Exactly one `current` version per document (71 current, 253 superseded).
