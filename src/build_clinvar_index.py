"""Clean ClinVar raw parquet, chunk, embed, and write Chroma collection."""

import json
from pathlib import Path

import chromadb
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

project_root = Path(__file__).resolve().parents[1]
data_raw = project_root / "data/raw"
data_processed = project_root / "data/processed"
chroma_dir = project_root / "data/chroma_db"

CLINVAR_RAW = data_raw / "clinvar_reliable_grch38.parquet"
CLINVAR_CLEAN = data_processed / "clinvar_rag.parquet"
CLINVAR_EXPORT = data_processed / "docs_for_rag_clinvar.jsonl"
CLINVAR_EMBEDDINGS = data_processed / "clinvar_chunk_embeddings.npy"
CLINVAR_COLLECTION = "clinvar_chunks"

CHUNK_MODE = "merged"  # "merged" | "by_field"
CHROMA_BATCH_SIZE = 5000
EMBED_BATCH_SIZE = 64
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

FIELD_SPECS = [
    ("gene", "GeneSymbol"),
    ("pathogenicity", "ClinicalSignificance"),
    ("impact", "PhenotypeList"),
    ("variant type", "Type"),
    ("reliablity", "ReviewStatus"),
]


def _is_valid_field(val) -> bool:
    if pd.isna(val):
        return False
    s = str(val).strip().lower()
    return bool(s) and s != "nan"


def _col_value(row, column: str) -> str:
    return str(row[column]) if _is_valid_field(row.get(column)) else ""


def _row_field_values(row) -> dict:
    field_values = {chunk_type: _col_value(row, col) for chunk_type, col in FIELD_SPECS}
    field_values["impact"] = _col_value(row, "PhenotypeList")
    return field_values


def build_chunked_docs(dataframe: pd.DataFrame, chunk_mode: str) -> list:
    chunked = []
    for _, row in dataframe.iterrows():
        variation_id = str(row["VariationID"])
        field_values = _row_field_values(row)
        gene = field_values["gene"]
        header = f"Variation: {variation_id}"

        if chunk_mode == "by_field":
            chunked.append({
                "id": f"{variation_id}_identity",
                "text": f"{header}\nType: identity",
                "metadata": {"variation_id": variation_id, "chunk_type": "identity", "gene": gene},
            })
            for chunk_type, column in FIELD_SPECS:
                value = field_values[chunk_type]
                if not value:
                    continue
                chunked.append({
                    "id": f"{variation_id}_{chunk_type.replace(' ', '_')}",
                    "text": f"{header}\nType: {chunk_type}\n{value}",
                    "metadata": {
                        "variation_id": variation_id,
                        "chunk_type": chunk_type,
                        "gene": gene,
                        column: value,
                    },
                })
        else:
            summary_lines = [
                f"{chunk_type}: {field_values[chunk_type]}"
                for chunk_type, _ in FIELD_SPECS
                if field_values[chunk_type]
            ]
            if not summary_lines:
                continue
            metadata = {
                "variation_id": variation_id,
                "chunk_type": "summary",
                "gene": gene,
            }
            for chunk_type, column in FIELD_SPECS:
                if field_values[chunk_type]:
                    metadata[column] = field_values[chunk_type]
            chunked.append({
                "id": f"{variation_id}_summary",
                "text": f"{header}\nType: summary\n" + "\n".join(summary_lines),
                "metadata": metadata,
            })
    return chunked


# --- load & clean ---
df = pd.read_parquet(CLINVAR_RAW)

df["PhenotypeList"] = df["PhenotypeList"].apply(
    lambda x: "not provided"
    if pd.isna(x)
    else str(x)
    .replace("not provided|", "")
    .replace("not specified|", "")
    .replace("|not provided", "")
    .replace("|not specified", "")
    .replace("not specified", "not provided")
    .replace("|", ". ")
)

df = df[df["ReviewStatus"].isin(["practice guideline", "reviewed by expert panel"])].copy()
df = df[df["ClinicalSignificance"] != "Uncertain significance"].copy()
df = df[df["Type"] == "single nucleotide variant"].copy()

data_processed.mkdir(parents=True, exist_ok=True)
df.to_parquet(CLINVAR_CLEAN, index=False)
print("Saved cleaned parquet:", CLINVAR_CLEAN, df.shape)

# --- chunk, embed, chroma ---
docs = build_chunked_docs(df, chunk_mode=CHUNK_MODE)
print(f"Chunk mode: {CHUNK_MODE}")
print(f"Built {len(docs)} chunks from {len(df)} variants (~{len(docs) / len(df):.1f} chunks/variant)")

chroma_dir.mkdir(parents=True, exist_ok=True)

with CLINVAR_EXPORT.open("w", encoding="utf-8") as f:
    for d in docs:
        f.write(json.dumps({"id": d["id"], "text": d["text"], "metadata": d["metadata"]}, ensure_ascii=False) + "\n")
print("Wrote", CLINVAR_EXPORT)

ids = [d["id"] for d in docs]
documents = [d["text"] for d in docs]
metadatas = [d["metadata"] for d in docs]

model = SentenceTransformer(EMBED_MODEL)
embeddings = model.encode(
    documents,
    batch_size=EMBED_BATCH_SIZE,
    show_progress_bar=True,
    convert_to_numpy=True,
)
np.save(CLINVAR_EMBEDDINGS, embeddings)
print("Saved embeddings:", CLINVAR_EMBEDDINGS)

client = chromadb.PersistentClient(path=str(chroma_dir))
try:
    client.delete_collection(CLINVAR_COLLECTION)
except Exception:
    pass
collection = client.create_collection(CLINVAR_COLLECTION)
for i in range(0, len(ids), CHROMA_BATCH_SIZE):
    collection.add(
        ids=ids[i : i + CHROMA_BATCH_SIZE],
        documents=documents[i : i + CHROMA_BATCH_SIZE],
        embeddings=embeddings[i : i + CHROMA_BATCH_SIZE].tolist(),
        metadatas=metadatas[i : i + CHROMA_BATCH_SIZE],
    )
print(f"Indexed {len(ids)} chunks -> {CLINVAR_COLLECTION}")
