# Phase 3: Version-Aware Hybrid Retrieval

## 1. Database-Level Hybrid Search Function
The PostgreSQL SQL function `search_chunks(q_emb, q_text, mode, as_of, k)` combines dense vector similarity with lexical search directly inside Supabase, enforcing temporal validity before fusion.

- **Vector Search**: pgvector cosine distance (`embedding <=> q_emb`), retrieving top 50 matches.
- **Full-Text Search**: Native PostgreSQL full-text search with English stemming (`to_tsquery('english', q_text)` using OR-constructed tokens for high recall), retrieving top 50 matches ranked by `ts_rank`.
- **Reciprocal Rank Fusion (RRF)**: Fuses vector and lexical rankings with smoothing constant $k = 60$:
  $$RRF\_score = \frac{1}{60 + r_{vec}} + \frac{1}{60 + r_{fts}}$$
- **Temporal Validity Filtering**: Applied in a single SQL CTE (`eligible`) before vector and full-text ranking:
  - **`current` mode**: `v.status = 'current'` — restricts search strictly to actively enforced document versions.
  - **`as_of` mode**: `v.effective_date <= as_of AND (v.expiry_date IS NULL OR v.expiry_date > as_of)` — reconstructs document state at a specific historical point in time.
  - **`all` mode**: No temporal filter — searches across all historical and current versions for evolution and change detection queries.

## 2. Intent Detection & Query Pipeline (`scripts/retrieve.py`)
- **Intent Parsing via Regex**:
  - **Explicit Date** $\rightarrow$ `as_of` mode: Extracts ISO (`YYYY-MM-DD`), month/year (`March 2025` $\rightarrow$ last day of month), or year-only patterns.
  - **Historical Evolution Keywords** $\rightarrow$ `all` mode: Matches phrases such as `what changed`, `history`, `over time`, `older versions`, `changes in`.
  - **Default** $\rightarrow$ `current` mode: Standard policy questions resolve to the latest active policies.
- **Query Embedding**: Queries are embedded with the BAAI query instruction prefix:
  `Represent this sentence for searching relevant passages: `
  via local `bge-small-en-v1.5` embeddings (384 dimensions).
- **Metadata Output**: Every retrieved chunk includes full lineage: document title, version label (`v1`, `v2`, ...), effective date, expiry date, status (`current` or `superseded`), and section path.

## 3. Validation & Evaluation Results
- **Intent Classification Accuracy**: **108 / 108 (100%)** accuracy tested against `data/synthetic/questions.json`.
- **Manual Verification**:
  1. **`current` mode** (*"What is the meal allowance?"*): Correctly returned only active (`current`) versions across company policies and FAQs, excluding superseded terms.
  2. **`all` / History mode** (*"What changed in the leave policy?"*): Successfully retrieved historical evolutions across multiple versions (`v1`, `v2`, etc.) of the same documents.
  3. **`as_of` mode** (*"What was the meal allowance as of March 2025?"*): Parsed target date as `2025-03-31` and retrieved only versions in force at that specific date.
