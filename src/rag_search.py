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


def _tag_hits(hits, source):
    tagged = []
    for hit in hits:
        tagged.append({**hit, "source": source})
    return tagged


def print_combined_retrieval_summary(
    query, top_k_chunks, top_k_results, per_source, combined_ranked,
):
    print(f"\n{'=' * 60}")
    print("COMBINED RETRIEVAL")
    print(f"{'=' * 60}")
    print(f"Query: {query}")
    for source_name, data in per_source.items():
        total = sum(len(v) for v in data["chunks_by_group"].values())
        n_groups = len(data["chunks_by_group"])
        print(
            f"  {source_name}: top {top_k_chunks} chunks → "
            f"{total} chunk(s) across {n_groups} record(s)"
        )
    print(
        f"\nCombined ranking: each record's best (lowest-distance) chunk is scored, "
        f"then the top {top_k_results} records across all sources are sent to the LLM "
        f"(one full parquet row per record)."
    )
    source_counts = {}
    for hit in combined_ranked:
        source_counts[hit["source"]] = source_counts.get(hit["source"], 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items()))
    print(f"Top {top_k_results} breakdown: {breakdown}")


def print_combined_hits(ranked):
    print(f"\n{'=' * 60}")
    print(f"TOP {len(ranked)} RECORD(S) (combined cross-source ranking)")
    print(f"{'=' * 60}")
    print("Preview below is the closest chunk only (truncated to 500 chars).\n")
    for rank, hit in enumerate(ranked, 1):
        meta = hit["metadata"] or {}
        source = hit["source"]
        dist = hit["distance"]
        chunk_type = meta.get("chunk_type", "?")
        if source == "clinvar":
            label = f"variation_id={meta.get('variation_id')} gene={meta.get('gene')}"
        else:
            label = (
                f"entry_name={meta.get('entry_name')} "
                f"accession={meta.get('accession')} gene={meta.get('gene')}"
            )
        print(f"{rank}. [{source}] {label} best_chunk={chunk_type} dist={dist:.4f}")
        print(hit["text"][:500] + ("..." if len(hit["text"]) > 500 else ""))
        print()


def search_combined(
    query,
    configs,
    top_k_chunks,
    top_k_results,
    chroma_dir,
    embed_model,
    verbose=True,
):
    # configs: dict mapping source name -> search config (same shape as search())
    # returns dict with query, ranked, per_source, records_by_source, context
    client = chromadb.PersistentClient(path=str(chroma_dir))
    per_source = {}
    candidates = []

    for source_name, config in configs.items():
        collection = client.get_collection(config["collection_name"])
        if verbose:
            print(f"Collection {config['collection_name']}: {collection.count()} chunks")

        chunks_by_group, best_by_group = query_and_group(
            collection, embed_model, query, top_k_chunks, config["group_key"],
        )
        per_source[source_name] = {
            "config": config,
            "chunks_by_group": chunks_by_group,
            "best_by_group": best_by_group,
        }
        candidates.extend(_tag_hits(best_by_group.values(), source_name))

    combined_ranked = sorted(candidates, key=lambda x: x["distance"])[:top_k_results]

    if verbose:
        print_combined_retrieval_summary(
            query, top_k_chunks, top_k_results, per_source, combined_ranked,
        )
        print_combined_hits(combined_ranked)

    records_by_source = {}
    sections = []
    for rank, hit in enumerate(combined_ranked, 1):
        source_name = hit["source"]
        config = per_source[source_name]["config"]
        record_id_cast = config.get("record_id_cast", str)
        meta = hit.get("metadata") or {}
        record_id = record_id_cast(meta.get(config["record_id_meta_key"]))

        if source_name not in records_by_source:
            records_df = pd.read_parquet(config["parquet_path"])
            records_by_source[source_name] = records_df
        else:
            records_df = records_by_source[source_name]

        row = records_df.loc[records_df[config["record_id_column"]] == record_id]
        full_record = (
            format_record(row.iloc[0], config["record_fields"])
            if len(row) else "(record not found)"
        )
        header = config["section_header_template"].format(rank=rank, **meta)
        source_tag = source_name.upper()
        sections.append(
            f"[{source_tag}] {header}\n\n"
            f"{config['full_record_label']}:\n{full_record}"
        )

    context = f"User query: {query}\n\n" + "\n\n---\n\n".join(sections)
    if verbose:
        print_context_preview(context, top_k_results)

    return {
        "query": query,
        "ranked": combined_ranked,
        "per_source": per_source,
        "records_by_source": records_by_source,
        "context": context,
    }
