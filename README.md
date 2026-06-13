# Genomic RAG Assistant

Semantic search and summarization over curated **ClinVar** variants and **UniProt** human reviewed proteins. Raw data is downloaded with simple scripts, cleaned and indexed into ChromaDB, then queried from Jupyter notebooks with local LLM or OpenAI API summarization.

## Pipeline

```
ingest_*.py       →  data/raw/
build_*_index.py  →  data/processed/ + data/chroma_db/
*_rag.ipynb       →  query → retrieve → summarize
combined_rag.ipynb →  cross-source search (ClinVar + UniProt)
*_eda.ipynb       →  exploration only
```

### ClinVar

```bash
python src/ingest_clinvar.py
python src/build_clinvar_index.py
```

- **Raw:** `data/raw/clinvar_reliable_grch38.parquet` (GRCh38, with consistent pathogenicity assessment, from NCBI)
- **Cleaned:** `data/processed/clinvar_rag.parquet` (~11.7k variants: non-VUS, SNV)
- **Chroma collection:** `clinvar_chunks` (1 merged chunk per variant)

### UniProt

```bash
python src/ingest_uniprot.py
python src/build_uniprot_index.py
```

- **Raw:** `data/raw/uniprot_human_reviewed.parquet`
- **Cleaned:** `data/processed/uniprot_rag.parquet` (~5.3k proteins with disease involvement)
- **Chroma collection:** `protein_chunks` (by-field chunks: identity, function, disease, expression)

Both index scripts also write `docs_for_rag_*.jsonl` and `*_chunk_embeddings.npy` under `data/processed/`.

## Query notebooks

Open and run top to bottom:

| Notebook | Purpose |
|---|---|
| `notebooks/clinvar_rag.ipynb` | Prompt for a query, search Chroma, build context from top hits, summarize |
| `notebooks/uniprot_rag.ipynb` | Same flow for proteins |
| `notebooks/combined_rag.ipynb` | Search both collections, rank records globally, summarize with ClinVar + UniProt context |

**Single-source notebooks** use `search()` from `rag_search.py`. **Combined search** uses `search_combined()`: each source is queried independently, records are scored by their best (lowest-distance) chunk, then the top results across ClinVar and UniProt are merged and sent to the LLM (one full parquet row per record).

Notebooks load only the **top-ranked records** from the processed parquet (not the full dataset) to keep memory use low.

Set `SUMMARIZER_BACKEND` in each RAG notebook:

| Backend | Model | Notes |
|---|---|---|
| `"local"` (default) | `Qwen/Qwen2.5-0.5B-Instruct` | ~2GB RAM; use 3B only with 8GB+ RAM. GPU recommended for larger models. |
| `"openai"` | `gpt-4o-mini` | Requires `OPENAI_API_KEY` in `.env`. No local model load. |

To inspect retrieval without summarization, stop after the search cell and use `result["context"]`.

## EDA notebooks

| Notebook | Purpose |
|---|---|
| `notebooks/clinvar_eda.ipynb` | ClinVar value counts, phenotype cleaning |
| `notebooks/uniprot_eda.ipynb` | UniProt head, gene lookup, fields for RAG |

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
  ingest_clinvar.py       # download ClinVar → raw parquet
  ingest_uniprot.py       # download UniProt → raw parquet
  build_clinvar_index.py  # clean, filter, chunk, embed, Chroma
  build_uniprot_index.py
  rag_search.py           # vector search, context building, combined search
  rag_summary.py          # LLM load + summarization
notebooks/
  clinvar_eda.ipynb
  clinvar_rag.ipynb
  uniprot_eda.ipynb
  uniprot_rag.ipynb
  combined_rag.ipynb
data/
  raw/          # downloaded parquets
  processed/    # cleaned parquets, jsonl exports, embeddings
  chroma_db/    # persistent vector store
```

## Tech

- **Embeddings:** `BAAI/bge-small-en-v1.5` (sentence-transformers)
- **Vector store:** ChromaDB
- **Summarization:** local `Qwen/Qwen2.5-0.5B-Instruct` (transformers + PyTorch) or OpenAI `gpt-4o-mini`

Chunking mode can be changed via `CHUNK_MODE` at the top of each `build_*_index.py` script (`"merged"` or `"by_field"`).
