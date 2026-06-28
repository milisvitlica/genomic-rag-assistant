# Genomic RAG Assistant

Semantic search and summarization over curated **ClinVar** variants and **UniProt** human reviewed proteins. Raw data is downloaded with simple scripts, cleaned and indexed into ChromaDB, then queried from Jupyter notebooks with local LLM or OpenAI API summarization.

## Pipeline

```
ingest_*.py          →  data/raw/
build_*_index.py     →  data/processed/ + data/chroma_db/ (cosine space)
build_joined_dataset.py →  data/processed/joined.parquet (EDA-only outer join)
rag.ipynb            →  query → retrieve → summarize (ClinVar, UniProt, or both)
*_eda.ipynb          →  exploration + scope characterization
```



## Getting started (first time)

From the project root.

**1. Install dependencies** (Python 3.10+). Use any environment manager you like — the only required step is:

```bash
pip install -r requirements.txt
```

A virtual environment is recommended to keep dependencies isolated, e.g.:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

**2. Build the data + vector index.** Each source needs an ingest step (downloads raw data) followed by an index step (cleans, chunks, embeds into ChromaDB). Run both:

```bash
# ClinVar variants
python src/ingest_clinvar.py
python src/build_clinvar_index.py

# UniProt proteins
python src/ingest_uniprot.py
python src/build_uniprot_index.py
```

This populates `data/raw/`, `data/processed/`, and `data/chroma_db/`. You only need to rerun these when you want to refresh the underlying data.

**3. Choose your summarizer.** Set `SUMMARIZER_BACKEND` in the notebook to `"local"` (a small model, no key needed) or `"openai"`. For OpenAI, add your API key to `.env`:

```bash
OPENAI_API_KEY=sk-...
```

**4. Query.** Open `notebooks/rag.ipynb`, set `query` and `SOURCES`, and run top to bottom:

```python
query = "What can we learn about telomere extension?"
SOURCES = ["clinvar", "uniprot"]   # or ["clinvar"] / ["uniprot"] for a single source
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



## Query notebook

`notebooks/rag.ipynb` is the single entry point for querying. Open it and run top to bottom.

Set two knobs at the top:

- `query` — the natural-language question.
- `SOURCES` — which collections to search: `["clinvar", "uniprot"]` (both), `["clinvar"]`, or `["uniprot"]`.

It uses `search_combined()` from `rag_search.py`: each selected source is queried independently, records are scored by their best chunk's **cosine similarity**, then the top results across the selected sources are merged and sent to the LLM (one full parquet row per record). With a single source this is just that source's ranking.

**Relevance gate.** `search_combined(..., min_similarity=...)` drops records whose best cosine similarity falls below a threshold. Off-topic / nonsense queries then retrieve nothing, the context becomes an explicit "no evidence" message, and the notebook abstains without an LLM call. Each record's similarity is also shown in the retrieval summary and passed into the LLM context. `MIN_SIMILARITY` is calibrated on this corpus (real queries ~0.67–0.86, nonsense ~0.41–0.53).

`TOP_K_CHUNKS` is the chunk pool used for ranking; `TOP_K_RESULTS` is how many full records reach the LLM. The pool is wider than the result count because multi-chunk records collapse to one and the two sources are merged before the final cut.

The notebook loads only the **top-ranked records** from the processed parquet (not the full dataset) to keep memory use low.

Chunking mode can be changed via `CHUNK_MODE` at the top of each `build_*_index.py` script (`"merged"` or `"by_field"`).

Set `SUMMARIZER_BACKEND` in the RAG notebook:


| Backend    | Model                        | Notes                                                                   |
| ---------- | ---------------------------- | ----------------------------------------------------------------------- |
| `"local"`  | `Qwen/Qwen2.5-0.5B-Instruct` | ~2GB RAM; use 3B only with 8GB+ RAM. GPU recommended for larger models. |
| `"openai"` | `gpt-4o-mini`                | Requires `OPENAI_API_KEY` in `.env`. No local model load.               |


To inspect retrieval without summarization, stop after the search cell and use `result["context"]`. After summarization, the notebook appends via `append_rag_report()`:

- `reports/rag_log.md` — query, timestamp, search mode, summarizer, summary (tracked in git)
- `data/reports/rag_log.csv` — same fields plus ranked hits (JSON) and full LLM context (gitignored)



## EDA notebooks


| Notebook                      | Purpose                                                           |
| ----------------------------- | ----------------------------------------------------------------- |
| `notebooks/clinvar_eda.ipynb` | ClinVar value counts, phenotype cleaning, scope characterization  |
| `notebooks/uniprot_eda.ipynb` | UniProt head, gene lookup, fields for RAG, scope characterization |
| `notebooks/joined_eda.ipynb`  | Outer-join impact, fan-out, match types, combined scope           |


Each EDA notebook has a **scope characterization** section (counts, field coverage, topical themes, free-text reachability) that feeds `docs/scope.md` — the data-derived description of what the RAG can and cannot answer. Regenerate `docs/scope.md` from these sections whenever the data is rebuilt.

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
  rag.ipynb        # query → retrieve → summarize (ClinVar, UniProt, or both)
  clinvar_eda.ipynb
  uniprot_eda.ipynb
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
- **Larger summarizer LLM (optional).** `gpt-4o-mini` is sufficient for grounded summarization; offer `gpt-4o`/`gpt-4.1` as a high-faithfulness toggle for clinical queries. Reasoning-tier models are overkill here.
- **RAG on the joined data.** Promote `joined.parquet` from EDA-only to a gene-centric RAG (one record per gene = protein context + its clinical variants) for deterministic protein↔variant linkage on the ~142 overlapping genes.
- **Logging for evaluation.** Add `abstained` / `gate_reason` columns to `rag_log.csv` to audit false abstentions and tune thresholds over time.

