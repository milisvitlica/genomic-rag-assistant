"""Format and append RAG search + summary outputs to markdown and CSV reports."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

_REPORT_HEADER = (
    "# RAG Query Log\n\n"
    "Automated exports from genomic RAG notebooks.\n"
)

_CSV_FIELDS = [
    "query",
    "timestamp",
    "search_mode",
    "summarizer_backend",
    "summarizer_model",
    "summary",
    "ranked_hits",
    "llm_context",
]


def _detect_search_mode(result):
    if "records_by_source" in result or "per_source" in result:
        return "combined"
    return "single"


def _infer_source_name(hit):
    meta = hit.get("metadata") or {}
    if "variation_id" in meta:
        return "clinvar"
    if "entry_name" in meta or "accession" in meta:
        return "uniprot"
    return None


def _hit_label(hit, source=None):
    meta = hit.get("metadata") or {}
    source = source or hit.get("source") or _infer_source_name(hit)
    if source == "clinvar":
        return f"variation_id={meta.get('variation_id')}, gene={meta.get('gene')}"
    if source == "uniprot":
        return (
            f"entry_name={meta.get('entry_name')}, "
            f"accession={meta.get('accession')}, gene={meta.get('gene')}"
        )
    return ", ".join(f"{k}={v}" for k, v in sorted(meta.items()))


def _search_label(search_mode, source_name, result):
    if search_mode == "combined":
        return "combined (ClinVar + UniProt)"
    ranked = result.get("ranked", [])
    if source_name:
        return source_name
    if ranked:
        return _infer_source_name(ranked[0]) or "single-source"
    return "single-source"


def _summarizer_label(backend, model_name):
    if model_name:
        return f"{backend} (`{model_name}`)"
    return backend


def _run_metadata(
    query,
    result,
    summary,
    *,
    search_mode=None,
    source_name=None,
    summarizer_backend="local",
    model_name=None,
):
    search_mode = search_mode or _detect_search_mode(result)
    return {
        "query": query,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "search_mode": _search_label(search_mode, source_name, result),
        "summarizer_backend": summarizer_backend,
        "summarizer_model": model_name or "",
        "summary": summary or "",
    }


def _serialize_ranked_hits(ranked):
    hits = []
    for rank, hit in enumerate(ranked, 1):
        meta = hit.get("metadata") or {}
        source = hit.get("source") or _infer_source_name(hit)
        hits.append({
            "rank": rank,
            "source": source,
            "label": _hit_label(hit, source),
            "distance": round(hit["distance"], 4),
            "chunk_type": meta.get("chunk_type", ""),
            "chunk_preview": hit["text"],
        })
    return hits


def format_rag_report(
    query,
    result,
    summary=None,
    *,
    search_mode=None,
    source_name=None,
    summarizer_backend="local",
    model_name=None,
):
    meta = _run_metadata(
        query,
        result,
        summary,
        search_mode=search_mode,
        source_name=source_name,
        summarizer_backend=summarizer_backend,
        model_name=model_name,
    )

    lines = [
        "---",
        "",
        f"## Query: {meta['query']}",
        "",
        (
            f"**Run:** {meta['timestamp']} · **Search:** {meta['search_mode']} · "
            f"**Summarizer:** {_summarizer_label(meta['summarizer_backend'], meta['summarizer_model'])}"
        ),
        "",
    ]

    if meta["summary"]:
        lines.extend([
            "### Summary",
            "",
            meta["summary"],
            "",
        ])

    return "\n".join(lines)


def _build_csv_row(
    query,
    result,
    summary=None,
    *,
    search_mode=None,
    source_name=None,
    summarizer_backend="local",
    model_name=None,
):
    meta = _run_metadata(
        query,
        result,
        summary,
        search_mode=search_mode,
        source_name=source_name,
        summarizer_backend=summarizer_backend,
        model_name=model_name,
    )
    return {
        "query": meta["query"],
        "timestamp": meta["timestamp"],
        "search_mode": meta["search_mode"],
        "summarizer_backend": meta["summarizer_backend"],
        "summarizer_model": meta["summarizer_model"],
        "summary": meta["summary"],
        "ranked_hits": json.dumps(
            _serialize_ranked_hits(result.get("ranked", [])),
            ensure_ascii=False,
        ),
        "llm_context": result.get("context", ""),
    }


def append_rag_csv(
    path,
    query,
    result,
    summary=None,
    *,
    search_mode=None,
    source_name=None,
    summarizer_backend="local",
    model_name=None,
):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = _build_csv_row(
        query,
        result,
        summary,
        search_mode=search_mode,
        source_name=source_name,
        summarizer_backend=summarizer_backend,
        model_name=model_name,
    )

    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"Appended RAG CSV row to {path.name}")
    return path


def append_rag_report(
    path,
    query,
    result,
    summary=None,
    *,
    search_mode=None,
    source_name=None,
    summarizer_backend="local",
    model_name=None,
    csv_path=None,
):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    entry = format_rag_report(
        query,
        result,
        summary,
        search_mode=search_mode,
        source_name=source_name,
        summarizer_backend=summarizer_backend,
        model_name=model_name,
    )

    if path.exists():
        content = path.read_text(encoding="utf-8").rstrip() + "\n\n" + entry
    else:
        content = _REPORT_HEADER + "\n" + entry

    path.write_text(content, encoding="utf-8")
    print(f"Appended RAG report to {path.name}")

    csv_path = Path(csv_path) if csv_path else path.with_suffix(".csv")
    append_rag_csv(
        csv_path,
        query,
        result,
        summary,
        search_mode=search_mode,
        source_name=source_name,
        summarizer_backend=summarizer_backend,
        model_name=model_name,
    )

    return path
