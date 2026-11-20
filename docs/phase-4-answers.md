# Phase 4: Version-Aware Answer Generation

## 1. LLM Integration (`scripts/llm.py`)
- **Provider**: Google GenAI SDK (`google-genai`).
- **Model Configuration**: Reads `GEMINI_MODEL` from `.env`, defaulting to `gemini-3.8-flash`.
- **Fault Tolerance**: Automatic exponential backoff retry mechanism (retrying on transient HTTP 429, 500, and 503 errors).
- **Encapsulation**: Serves as the single centralized entry point for model generation across the repository.

## 2. Version-Aware Answer Engine (`scripts/answer.py`)
The answer pipeline grounds responses strictly in temporal context:
- **System Prompt Rules**:
  1. Answer using **only** numbered sources (`[1]`, `[2]`).
  2. Always explicitly cite the source's **document version label and effective date** (e.g., `(Travel Policy v3, effective 2024-02-27)`).
  3. Flag any discrepancies or contradictions between versions/documents and state which version is current.
  4. For historical evolution questions, list changes in chronological order (old value $\rightarrow$ new value).
  5. Refuse to guess or hallucinate if sources lack the answer.
  6. Maintain concise responses (2–5 sentences unless chronological detail requires more).

## 3. History Retrieval Routing (`scripts/history.py`)
History questions (*"What changed..."*, *"How has X changed..."*) require full longitudinal visibility across all versions of a single document rather than generic cross-document snippet retrieval:
- **Document Identification (`pick_doc`)**: Matches document title against the question (stripping stop words and excluding FAQ documents unless specifically requested).
- **Cross-Version Extraction**: Identifies candidate document IDs and extracts the top 4 chunks per version using dense similarity, partitioned by `version_id` and ordered chronologically (`effective_date`, `chunk_index`).
- **Sequential Context**: Provides the LLM with chronological lineage from the earliest version (`v1`) to the latest (`current`), allowing clear pairwise delta computation.

## 4. Manual Verification & Observations
- **`current` Mode** (*"What is the meal allowance at Crestline Financial?"*):
  - Correctly resolved to `Crestline Financial - Travel and Expense Policy FAQ (v2, effective 2024-04-12, current)` with the active limit of $75/day.
- **`as_of` Mode** (*"What was the meal allowance at Crestline Financial as of January 2024?"*):
  - Correctly isolated the version in force as of January 2024 (`v3`, effective 2023-07-28, $75/day).
  - **Surfaced Conflict**: Identified a disagreement with an older FAQ v1 ($60/day) that had not been updated simultaneously—a real-world stale FAQ contradiction to be systematically detected in Phase 5.
- **`all` / History Mode** (*"What changed in the Crestline Financial travel policy?"* and *"How has the meal allowance changed at Northwind Labs?"*):
  - Correctly traced version-by-version transitions:
    - Crestline Financial Travel Policy: Mileage 55¢ $\rightarrow$ 30¢ (v1 $\rightarrow$ v2); Meals $60 $\rightarrow$ $75 & Mileage 30¢ $\rightarrow$ 55¢ (v2 $\rightarrow$ v3); Receipts $50 $\rightarrow$ $10 (v3 $\rightarrow$ v4).
    - Northwind Labs Travel Policy: Traced meal allowance from $75 in v1 and v2 down to $50 in v3 (current).
