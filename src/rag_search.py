"""Generic RAG vector search and context building."""

import chromadb
import pandas as pd


def format_record(row, fields):
    # row: pandas Series, fields: list of column names -> str
    return "\n".join(
        f"{col}: {row[col]}"
        for col in fields
        if col in row.index and pd.notna(row[col])
    )


def query_and_group(collection, embed_model, query, top_k_chunks, group_key):
    # collection: chromadb collection, embed_model: SentenceTransformer
    # returns (chunks_by_group dict, best_by_group dict)
    results = collection.query(
        query_embeddings=[embed_model.encode(query).tolist()],
        n_results=top_k_chunks,
        include=["documents", "metadatas", "distances"],
    )

    chunks_by_group = {}
    best_by_group = {}
    for doc_text, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0],
    ):
        key = (meta or {}).get(group_key)
        hit = {"text": doc_text, "metadata": meta, "distance": dist}
        chunks_by_group.setdefault(key, []).append(hit)
        if key not in best_by_group or dist < best_by_group[key]["distance"]:
            best_by_group[key] = hit
    return chunks_by_group, best_by_group


def print_retrieval_summary(top_k_chunks, chunks_by_group, ranked, top_k_results, group_key, query):
    total_retrieved = sum(len(v) for v in chunks_by_group.values())
    n_groups = len(chunks_by_group)
    selected_groups = {
        (h.get("metadata") or {}).get(group_key) for h in ranked
    }
    chunks_for_llm = sum(
        len(chunks_by_group.get(g, [])) for g in selected_groups
    )
    print(f"\n{'=' * 60}")
    print("RETRIEVAL")
    print(f"{'=' * 60}")
    print(f"Query: {query}")
    print(
        f"Chroma returned the top {top_k_chunks} matching chunks "
        f"({total_retrieved} chunks across {n_groups} unique record(s))."
    )
    print(
        f"Top {top_k_results} record(s) for the LLM: among proteins in this pool, "
        f"rank by each protein's best (lowest-distance) chunk, then take the top "
        f"{top_k_results}. Chunks are used for ranking only — the LLM gets one full "
        f"parquet row per selected record."
    )
    if chunks_for_llm < total_retrieved:
        print(
            f"({total_retrieved - chunks_for_llm} chunk(s) in the pool belong to "
            f"proteins outside the top {top_k_results}.)"
        )


def print_hits(query, ranked, chunks_by_group, group_key, hit_fields):
    # query: str, ranked: list of hits, chunks_by_group: dict
    # group_key: str (metadata field), hit_fields: list of (meta_key, label) tuples
    print(f"\n{'=' * 60}")
    print(f"TOP {len(ranked)} RECORD(S) (ranked by best-matching chunk per record)")
    print(f"{'=' * 60}")
    print("Preview below is the closest chunk only (truncated to 500 chars).\n")
    for rank, hit in enumerate(ranked, 1):
        meta = hit["metadata"] or {}
        group_val = meta.get(group_key)
        n_chunks = len(chunks_by_group.get(group_val, []))
        parts = [f"{label}={meta.get(key)}" for key, label in hit_fields]
        parts.append(f"best_chunk={meta.get('chunk_type')}")
        parts.append(f"dist={hit['distance']:.4f}")
        parts.append(f"({n_chunks} retrieved chunk(s))")
        print(f"{rank}. " + " ".join(parts))
        print(hit["text"][:500] + ("..." if len(hit["text"]) > 500 else ""))
        print()


def print_context_preview(context, top_k_results, preview_chars=4000):
    print(f"\n{'=' * 60}")
    print("LLM CONTEXT (what summarize() receives)")
    print(f"{'=' * 60}")
    print(
        f"Full context: {len(context):,} characters for {top_k_results} record(s). "
        f"Each section is one full parquet row (no chunk text)."
    )
    if len(context) > preview_chars:
        print(f"Notebook preview below is truncated to {preview_chars:,} chars; the LLM gets the full text.\n")
    else:
        print()
    print(context[:preview_chars] + ("..." if len(context) > preview_chars else ""))


def build_context(
    query,
    ranked,
    records_df,
    record_id_column,
    record_id_meta_key,
    record_fields,
    section_header_template,
    full_record_label,
    record_id_cast=str,
):
    # ranked: list of hits, records_df: pandas DataFrame, record_id_cast: callable (default str)
    # section_header_template: str with {rank} and metadata placeholders -> str
    sections = []
    for rank, hit in enumerate(ranked, 1):
        meta = hit.get("metadata") or {}
        record_id = record_id_cast(meta.get(record_id_meta_key))
        row = records_df.loc[records_df[record_id_column] == record_id]
        full_record = format_record(row.iloc[0], record_fields) if len(row) else "(record not found)"
        header = section_header_template.format(rank=rank, **meta)
        sections.append(f"{header}\n\n{full_record_label}:\n{full_record}")
    return f"User query: {query}\n\n" + "\n\n---\n\n".join(sections)


def search(
    query,
    config,
    top_k_chunks,
    top_k_results,
    chroma_dir,
    embed_model,
    verbose=True,
):
    # query: str, config: dict (see notebook SEARCH_CONFIG), chroma_dir: path str
    # embed_model: SentenceTransformer -> dict with query, ranked, chunks_by_group, records_df, context
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection(config["collection_name"])
    if verbose:
        print(f"Collection {config['collection_name']}: {collection.count()} chunks")

    chunks_by_group, best_by_group = query_and_group(
        collection, embed_model, query, top_k_chunks, config["group_key"],
    )
    ranked = sorted(best_by_group.values(), key=lambda x: x["distance"])[:top_k_results]

    if verbose:
        print_retrieval_summary(
            top_k_chunks, chunks_by_group, ranked, top_k_results,
            config["group_key"], query,
        )
        print_hits(
            query, ranked, chunks_by_group,
            config["group_key"],
            config["hit_fields"],
        )

    record_id_cast = config.get("record_id_cast", str)
    selected_ids = [
        record_id_cast((h["metadata"] or {}).get(config["record_id_meta_key"]))
        for h in ranked
    ]
    records_df = pd.read_parquet(config["parquet_path"])
    records_df = records_df[records_df[config["record_id_column"]].isin(selected_ids)].copy()

    context = build_context(
        query, ranked, records_df,
        config["record_id_column"],
        config["record_id_meta_key"],
        config["record_fields"],
        config["section_header_template"],
        config["full_record_label"],
        record_id_cast,
    )
    if verbose:
        print_context_preview(context, top_k_results)

    return {
        "query": query,
        "ranked": ranked,
        "chunks_by_group": chunks_by_group,
        "records_df": records_df,
        "context": context,
    }
