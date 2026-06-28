# Genomic RAG — Data Scope

This document defines what the RAG can and cannot answer. It is **derived from the indexed data**, not hand-written assumptions — regenerate it from the "Scope characterization" sections of `notebooks/clinvar_eda.ipynb`, `notebooks/uniprot_eda.ipynb`, and `notebooks/joined_eda.ipynb` whenever the data is rebuilt.

Scope has two layers:

- **Structural scope (hard boundary):** organism, sources, filters, record types, fields. Enumerable and authoritative.
- **Topical scope (soft / illustrative):** the biology that happens to appear in free-text fields. Open-ended — **any concept mentioned in the text below is retrievable**, even when it is not a gene or variant ID (e.g. "hemoglobin"). The lists here are representative samples, not an allow-list.

---


## Structural scope

### UniProt (collection `protein_chunks`)
- **Organism:** *Homo sapiens*, reviewed (Swiss-Prot) only.
- **Filter:** only proteins **with a disease-involvement annotation**.
- **Size:** 5,296 proteins (5,291 distinct primary genes).

### ClinVar (collection `clinvar_chunks`)
- **Assembly:** GRCh38 only.
- **Variant type:** single nucleotide variants (SNVs) only.
- **Review status:** expert-reviewed only — "reviewed by expert panel" (11,572) + "practice guideline" (19).
- **Clinical significance:** non-VUS only — Pathogenic 4,072 · Likely benign 2,700 · Benign 2,513 · Likely pathogenic 2,304 (+2 combined-label rows).
- **Size:** 11,591 variants across 178 genes.
- **Chromosomes:** 1–22, X, MT (no Y).
- **Fields:** HGVS `Name`, `GeneSymbol`, `ClinicalSignificance`, `PhenotypeList`, `ReviewStatus`, `Chromosome`/`Start`/`Stop`, `NumberSubmitters`, `VariationID`.

---

## Topical scope (illustrative)

### Diseases / phenotypes well covered
- **Hereditary cancer syndromes:** hereditary breast–ovarian cancer (BRCA1/2), Lynch syndrome / hereditary nonpolyposis colorectal cancer, familial breast cancer, hereditary diffuse gastric cancer (CDH1).
- **Metabolic:** monogenic diabetes / MODY, phenylketonuria, familial hypercholesterolemia, glycogen storage disease type II.
- **Other Mendelian:** cystic fibrosis (CFTR), Glanzmann thrombasthenia, limb-girdle muscular dystrophy, RASopathies, Leber congenital amaurosis, hereditary thrombocytopenia/hematologic cancer predisposition (RUNX1).
- **UniProt disease breadth:** ~6,800 distinct disease terms incl. many cancers, neurological (schizophrenia, Parkinson, ALS), and metabolic (type 2 diabetes, obesity) conditions.

### Free-text reachability (concept → records that mention it)
A topic is in scope wherever it appears in text, not only as an ID:

| Concept | UniProt rows | ClinVar rows |
|---|---|---|
| hemoglobin | 29 | 11 |
| cancer | 370 | 5,712 |
| diabetes / insulin | 205 | 33 |
| muscle | 1,399 | 8 |
| neuro* | 1,952 | 204 |
| immune | 720 | 302 |
| mitochondria* | 528 | 129 |
| retina | 484 | 183 |
| kinase | 574 | 1 |

---

## Out of scope (will not have reliable answers)

- **Variant classes other than SNVs** — indels, duplications, CNVs, structural variants (excluded at indexing).
- **Variants of uncertain significance (VUS)** and conflicting/low-confidence classifications (excluded).
- **Non-expert-reviewed ClinVar submissions.**
- **GRCh37 / hg19 coordinates** (only GRCh38 indexed).
- **Y-chromosome variants** (none present).
- **Unreviewed (TrEMBL) proteins**, and reviewed proteins **without** disease annotation.
- **Non-human** organisms.
- **Reasoning beyond the stored text:** pathway/mechanistic explanation, 3D structure coordinates, drug dosing or treatment guidance, population allele frequencies, prognosis, or any fact not written in the indexed fields.

---
