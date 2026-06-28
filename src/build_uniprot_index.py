"""Clean UniProt raw parquet, chunk, embed, and write Chroma collection."""

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

UNIPROT_RAW = data_raw / "uniprot_human_reviewed.parquet"
UNIPROT_CLEAN = data_processed / "uniprot_rag.parquet"
UNIPROT_EXPORT = data_processed / "docs_for_rag_uniprot.jsonl"
UNIPROT_EMBEDDINGS = data_processed / "uniprot_chunk_embeddings.npy"
UNIPROT_COLLECTION = "protein_chunks"

CHUNK_MODE = "by_field"  # "merged" | "by_field"
CHROMA_BATCH_SIZE = 5000
EMBED_BATCH_SIZE = 64
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

CHUNK_SPECS = [
    ("function", ["Function [CC]"]),
    ("disease", ["Involvement in disease"]),
    ("expression", ["Tissue specificity"]),
]


def _is_valid_field(val) -> bool:
    if pd.isna(val):
        return False
    s = str(val).strip().lower()
    return bool(s) and s != "nan"


def _col_value(row, column: str) -> str:
    if column not in row.index:
        return ""
    return str(row[column]) if _is_valid_field(row.get(column)) else ""


def _first_gene(gene_names) -> str:
    if not _is_valid_field(gene_names):
        return ""
    return str(gene_names).split()[0]


def _merged_chunk_text(row, columns: list[str]) -> str:
    parts = []
    for column in columns:
        value = _col_value(row, column)
        if value:
            parts.append(f"{column}:\n{value}")
    return "\n\n".join(parts)


def _build_header(row) -> tuple[str, str, str, int, str]:
    entry_name = _col_value(row, "Entry Name") or str(row["Entry"])
    accession = str(row["Entry"])
    gene = _first_gene(row["Gene Names"])
    protein = _col_value(row, "Protein names")
    length = int(row["Length"]) if pd.notna(row.get("Length")) else 0
    header = f"Entry name: {entry_name}\nAccession: {accession}"
    if gene:
        header += f"\nGene: {gene}"
    if protein:
        header += f"\nProtein: {protein}"
    if length:
        header += f"\nLength: {length}"
    return entry_name, accession, gene, length, header


def _chunk_body(row, columns: list[str]) -> str:
    if len(columns) == 1:
        return _col_value(row, columns[0])
    return _merged_chunk_text(row, columns)


def build_chunked_docs(dataframe: pd.DataFrame, chunk_mode: str) -> list:
    chunked = []
    for _, row in dataframe.iterrows():
        entry_name, accession, gene, length, header = _build_header(row)
        base_metadata = {
            "entry_name": entry_name,
            "accession": accession,
            "gene": gene,
            "length": length,
        }

        if chunk_mode == "by_field":
            chunk_specs = [("identity", ["Entry Name", "Gene Names", "Protein names", "Length"])] + CHUNK_SPECS
            for chunk_type, columns in chunk_specs:
                if chunk_type == "identity":
                    text = f"{header}\nType: identity"
                else:
                    body = _chunk_body(row, columns)
                    if not body:
                        continue
                    text = f"{header}\nType: {chunk_type}\n{body}"
                chunked.append({
                    "id": f"{entry_name}_{chunk_type}",
                    "text": text,
                    "metadata": {**base_metadata, "chunk_type": chunk_type},
                })
        else:
            summary_lines = []
            metadata = {**base_metadata, "chunk_type": "summary"}
            for chunk_type, columns in CHUNK_SPECS:
                body = _chunk_body(row, columns)
                if not body:
                    continue
                summary_lines.append(f"{chunk_type}: {body}")
                for column in columns:
                    value = _col_value(row, column)
                    if value:
                        metadata[column] = value
            if not summary_lines:
                continue
            chunked.append({
                "id": f"{entry_name}_summary",
                "text": f"{header}\nType: summary\n" + "\n".join(summary_lines),
                "metadata": metadata,
            })
    return chunked


# --- load & clean ---
df = pd.read_parquet(UNIPROT_RAW)

df["Function [CC]"] = df["Function [CC]"].str.replace("FUNCTION: ", "")
df["Involvement in disease"] = df["Involvement in disease"].str.replace("DISEASE: ", "")
df["Tissue specificity"] = df["Tissue specificity"].str.replace("TISSUE SPECIFICITY: ", "")

df = df[df["Involvement in disease"].notna()].copy()

data_processed.mkdir(parents=True, exist_ok=True)
df.to_parquet(UNIPROT_CLEAN, index=False)
print("Saved cleaned parquet:", UNIPROT_CLEAN, df.shape)

# --- chunk, embed, chroma ---
docs = build_chunked_docs(df, chunk_mode=CHUNK_MODE)
print(f"Chunk mode: {CHUNK_MODE}")
print(f"Built {len(docs)} chunks from {len(df)} proteins (~{len(docs) / len(df):.1f} chunks/protein)")

chroma_dir.mkdir(parents=True, exist_ok=True)

with UNIPROT_EXPORT.open("w", encoding="utf-8") as f:
    for d in docs:
        f.write(json.dumps({"id": d["id"], "text": d["text"], "metadata": d["metadata"]}, ensure_ascii=False) + "\n")
print("Wrote", UNIPROT_EXPORT)

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
np.save(UNIPROT_EMBEDDINGS, embeddings)
print("Saved embeddings:", UNIPROT_EMBEDDINGS)

client = chromadb.PersistentClient(path=str(chroma_dir))
try:
    client.delete_collection(UNIPROT_COLLECTION)
except Exception:
    pass
collection = client.create_collection(
    UNIPROT_COLLECTION,
    metadata={"hnsw:space": "cosine"},
)
for i in range(0, len(ids), CHROMA_BATCH_SIZE):
    collection.add(
        ids=ids[i : i + CHROMA_BATCH_SIZE],
        documents=documents[i : i + CHROMA_BATCH_SIZE],
        embeddings=embeddings[i : i + CHROMA_BATCH_SIZE].tolist(),
        metadatas=metadatas[i : i + CHROMA_BATCH_SIZE],
    )
print(f"Indexed {len(ids)} chunks -> {UNIPROT_COLLECTION}")
