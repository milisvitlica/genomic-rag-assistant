# Genomic RAG Assistant

Semantic search and summarization over curated **ClinVar** variants and **UniProt** human reviewed proteins. Raw data is downloaded with simple scripts, cleaned and indexed into ChromaDB, then queried from Jupyter notebooks with optional local LLM summarization.

## Pipeline

```
ingest_*.py       →  data/raw/
build_*_index.py  →  data/processed/ + data/chroma_db/
*_rag.ipynb       →  query → retrieve → summarize
*_eda.ipynb       →  exploration only
```

### ClinVar

```bash
python src/ingest_clinvar.py
python src/build_clinvar_index.py
```

- **Raw:** `data/raw/clinvar_reliable_grch38.parquet` (GRCh38, with consistant pathogenicity assesment, from NCBI)
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

Notebooks load only the **top-ranked records** from the processed parquet (not the full dataset) to keep memory use low. Set `LOAD_LLM = False` in the last cell to skip summarization.

Default LLM: `Qwen/Qwen2.5-7B-Instruct` (ungated). On CPU this needs ~14GB RAM; a GPU is recommended.

## EDA notebooks

| Notebook | Purpose |
|---|---|
| `notebooks/clinvar_eda.ipynb` | ClinVar value counts, phenotype cleaning|
| `notebooks/uniprot_eda.ipynb` | UniProt head, gene lookup, fields for RAG|

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Optional: set `HF_TOKEN` for Hugging Face model downloads.

## Project layout

```
src/
  ingest_clinvar.py       # download ClinVar → raw parquet
  ingest_uniprot.py       # download UniProt → raw parquet
  build_clinvar_index.py  # clean, filter, chunk, embed, Chroma
  build_uniprot_index.py
notebooks/
  clinvar_eda.ipynb
  clinvar_rag.ipynb
  uniprot_eda.ipynb
  uniprot_rag.ipynb
data/
  raw/          # downloaded parquets
  processed/    # cleaned parquets, jsonl exports, embeddings
  chroma_db/    # persistent vector store
```

## Tech

- **Embeddings:** `BAAI/bge-small-en-v1.5` (sentence-transformers)
- **Vector store:** ChromaDB
- **Summarization:** transformers + PyTorch (Qwen2.5 7B Instruct)

Chunking mode can be changed via `CHUNK_MODE` at the top of each `build_*_index.py` script (`"merged"` or `"by_field"`).
