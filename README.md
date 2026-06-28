# Genomic RAG Assistant

Semantic search and summarization over curated **ClinVar** variants and **UniProt** human reviewed proteins. Raw data is downloaded with simple scripts, cleaned and indexed into ChromaDB, then queried from Jupyter notebooks with local LLM or OpenAI API summarization.

## Pipeline

```
ingest_*.py          →  data/raw/
build_*_index.py     →  data/processed/ + data/chroma_db/ (cosine space)
build_joined_dataset.py →  data/processed/joined.parquet (EDA-only outer join)
*_rag.ipynb          →  query → retrieve → summarize
combined_rag.ipynb   →  cross-source search (ClinVar + UniProt) + relevance gate
*_eda.ipynb          →  exploration + scope characterization
```



### ClinVar

```bash
python src/ingest_clinvar.py
python src/build_clinvar_index.py
```

- **Raw:** `data/raw/clinvar_reliable_grch38.parquet` (GRCh38, with consistent pathogenicity assessment, from NCBI)
- **Cleaned:** `data/processed/clinvar_rag.parquet` (~11.6k variants: non-VUS, SNV, expert-reviewed)
- **Chroma collection:** `clinvar_chunks` (1 merged chunk per variant)



### UniProt

```bash
python src/ingest_uniprot.py
python src/build_uniprot_index.py
```

- **Raw:** `data/raw/uniprot_human_reviewed.parquet`
- **Cleaned:** `data/processed/uniprot_rag.parquet` (~5.3k proteins with disease involvement)
- **Chroma collection:** `protein_chunks` (by-field chunks: identity, function, disease, expression)

Both index scripts also write `docs_for_rag_*.jsonl` and `*_chunk_embeddings.npy` under `data/processed/`. Collections are created in **cosine** space (`hnsw:space=cosine`), matching how `bge` embeddings are meant to be compared.

### Joined dataset (EDA only)

```bash
python src/build_joined_dataset.py
```

Outer-joins the two cleaned parquets on **UniProt primary gene** (first token of `Gene Names`) = **ClinVar gene**. ClinVar `GeneSymbol` is a `;`-delimited gene list, so each variant is exploded to one gene per row before joining (original kept in `GeneSymbolFull`).

- **Output:** `data/processed/joined.parquet` (~16.8k rows): `both` (protein+variant), `uniprot_only`, `clinvar_only` rows flagged by `match_type`.
- Used by `notebooks/joined_eda.ipynb` only — **not** indexed or part of the RAG.



## Query notebooks

Open and run top to bottom:


| Notebook                       | Purpose                                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| `notebooks/clinvar_rag.ipynb`  | Prompt for a query, search Chroma, build context from top hits, summarize                |
| `notebooks/uniprot_rag.ipynb`  | Same flow for proteins                                                                   |
| `notebooks/combined_rag.ipynb` | Search both collections, rank records globally, summarize with ClinVar + UniProt context |


**Single-source notebooks** use `search()` from `rag_search.py`. **Combined search** uses `search_combined()`: each source is queried independently, records are scored by their best chunk's **cosine similarity**, then the top results across ClinVar and UniProt are merged and sent to the LLM (one full parquet row per record).

**Relevance gate.** `search_combined(..., min_similarity=...)` drops records whose best cosine similarity falls below a threshold. Off-topic / nonsense queries then retrieve nothing, the context becomes an explicit "no evidence" message, and the notebook abstains without an LLM call. Each record's similarity is also shown in the retrieval summary and passed into the LLM context. Calibrated default `MIN_SIMILARITY = 0.55` (real queries ~0.67–0.86, nonsense ~0.41–0.53).

`TOP_K_CHUNKS` (default 20) is the chunk pool used for ranking; `TOP_K_RESULTS` (default 3) is how many full records reach the LLM. The pool is wider than the result count because multi-chunk records collapse to one and the two sources are merged before the final cut.

Notebooks load only the **top-ranked records** from the processed parquet (not the full dataset) to keep memory use low.

Chunking mode can be changed via `CHUNK_MODE` at the top of each `build_*_index.py` script (`"merged"` or `"by_field"`).


Set `SUMMARIZER_BACKEND` in each RAG notebook:


| Backend             | Model                        | Notes                                                                   |
| ------------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `"local"` (default) | `Qwen/Qwen2.5-0.5B-Instruct` | ~2GB RAM; use 3B only with 8GB+ RAM. GPU recommended for larger models. |
| `"openai"`          | `gpt-4o-mini`                | Requires `OPENAI_API_KEY` in `.env`. No local model load.               |


To inspect retrieval without summarization, stop after the search cell and use `result["context"]`. After summarization, each notebook appends via `append_rag_report()`:

- `reports/rag_log.md` — query, timestamp, search mode, summarizer, summary (tracked in git)
- `data/reports/rag_log.csv` — same fields plus ranked hits (JSON) and full LLM context (gitignored)



## EDA notebooks


| Notebook                      | Purpose                                                           |
| ----------------------------- | ----------------------------------------------------------------- |
| `notebooks/clinvar_eda.ipynb` | ClinVar value counts, phenotype cleaning, scope characterization  |
| `notebooks/uniprot_eda.ipynb` | UniProt head, gene lookup, fields for RAG, scope characterization |
| `notebooks/joined_eda.ipynb`  | Outer-join impact, fan-out, match types, combined scope           |


Each EDA notebook has a **scope characterization** section (counts, field coverage, topical themes, free-text reachability) that feeds `docs/scope.md` — the data-derived description of what the RAG can and cannot answer. Regenerate `docs/scope.md` from these sections whenever the data is rebuilt.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For OpenAI summarization, add your API key to `.env`:

```bash
OPENAI_API_KEY=sk-...
```



## Project layout

```
src/
  ingest_clinvar.py        # download ClinVar → raw parquet
  ingest_uniprot.py        # download UniProt → raw parquet
  build_clinvar_index.py   # clean, filter, chunk, embed, Chroma (cosine)
  build_uniprot_index.py
  build_joined_dataset.py  # outer-join cleaned parquets → joined.parquet (EDA only)
  rag_search.py            # vector search, context building, combined search + relevance gate
  rag_summary.py           # LLM load + summarization
  rag_export.py            # append RAG outputs to markdown + CSV
notebooks/
  clinvar_eda.ipynb
  clinvar_rag.ipynb
  uniprot_eda.ipynb
  uniprot_rag.ipynb
  combined_rag.ipynb
  joined_eda.ipynb
docs/
  scope.md        # data-derived scope (what the RAG can/can't answer)
reports/
  rag_log.md      # RAG summary log (git-tracked)
data/
  raw/          # downloaded parquets
  processed/    # cleaned parquets, jsonl exports, embeddings, joined.parquet
  chroma_db/    # persistent vector store (cosine)
  reports/      # RAG CSV log (gitignored via data/)
```



## Tech

- **Embeddings:** `BAAI/bge-small-en-v1.5` (sentence-transformers)
- **Vector store:** ChromaDB (cosine space)
- **Summarization:** local `Qwen/Qwen2.5-0.5B-Instruct` (transformers + PyTorch) or OpenAI `gpt-4o-mini`



## Next steps

Ideas for improving answer quality and trustworthiness:

- **Scope router (pre-retrieval).** Use `docs/scope.md` (condensed to a ~200-token "router card") in a cheap LLM call to classify whether a query is in-domain *before* retrieving, and abstain early if not. Complements the cosine relevance gate (coarse routing vs. fine answerability).
- **Groundedness / answerability gate (post-retrieval).** After retrieval, an LLM judge confirms the retrieved records actually address the query (keyword overlap ≠ an answer) and returns the subset to cite; abstain otherwise. More robust than a distance threshold alone.
- **Threshold vs. k tuning.** Calibrate `MIN_SIMILARITY`, `TOP_K_CHUNKS`, and `TOP_K_RESULTS` on a labelled set of in/out-of-scope queries; consider a *relative* cutoff (keep records within ~0.05–0.08 similarity of the top hit) so sharp queries return more records and vague ones self-trim.
- **Reranking.** Add a cross-encoder reranker (e.g. `bge-reranker-base`) over the chunk pool for better-calibrated relevance than bi-encoder cosine, at some latency cost.
- **Larger summarizer LLM (optional).** Default `gpt-4o-mini` is sufficient for grounded summarization; offer `gpt-4o`/`gpt-4.1` as a high-faithfulness toggle for clinical queries. Reasoning-tier models are overkill here.
- **RAG on the joined data.** Promote `joined.parquet` from EDA-only to a gene-centric RAG (one record per gene = protein context + its clinical variants) for deterministic protein↔variant linkage on the ~142 overlapping genes.
- **Logging for evaluation.** Add `abstained` / `gate_reason` columns to `rag_log.csv` to audit false abstentions and tune thresholds over time.

