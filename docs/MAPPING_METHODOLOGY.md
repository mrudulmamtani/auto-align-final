# UAE IA → NIST SP 800-53 Semantic Mapping Engine

## Overview

This engine maps every UAE Information Assurance (IA) control to its corresponding NIST SP 800-53 Rev.5 control(s) using OpenAI's highest-accuracy embedding model. The relationship is **many-to-one from the NIST perspective**: NIST controls are atomic and canonical; UAE IA controls are compound (each covers a broader security objective that multiple NIST controls address together). Each NIST control is assigned to exactly one UAE IA control; one UAE IA control may receive many NIST controls.

---

## Inputs

| File | Description |
|------|-------------|
| `NIST.json.json` | NIST SP 800-53 Rev.5 catalog in OSCAL format — 20 control families, 1,196 controls (base + enhancements) |
| `uae.json` | UAE IA catalog in OSCAL format — 15 domains, 187 controls across 50 sub-domains |

---

## Engine: `openai_semantic_engine.py`

### Step 1 — Text Representation

Each control is serialised into a single structured text string that includes its hierarchical context and full prose. The template preserves domain/family context so the embedding reflects both topic and scope:

- **UAE IA**: `"[Domain Title] > [Subdomain Title]: [Control Title].  [Statement prose...]"`
- **NIST**: `"[Family Title]: [Control Title].  [Statement prose...]"`

All OSCAL parameter tokens (`{{...}}`) are stripped; whitespace is normalised. This ensures the model encodes security intent, not formatting artefacts.

### Step 2 — Embeddings

Model: **`text-embedding-3-large`** (OpenAI, 3,072 dimensions).

- All 187 UAE IA control texts are embedded once and cached to `oai_uae_vecs.pkl`.
- All 1,196 NIST control texts are embedded once and cached to `oai_nist_vecs.pkl`.
- Incremental partial-save logic (`*.pkl.partial`) ensures a restart after network failure resumes from the last completed batch rather than re-embedding from scratch.

`text-embedding-3-large` produces the highest-quality English-language semantic vectors available from OpenAI. At 3,072 dimensions it captures nuanced distinctions between, e.g., *audit logging* (operational) vs. *performance evaluation* (governance) that smaller models conflate.

### Step 3 — Cosine Similarity Matrix

```
raw_sim  =  cosine_similarity(nist_vecs, uae_vecs)   # shape (1196, 187)
```

Every entry `raw_sim[n, u]` is the pure semantic similarity between NIST control *n* and UAE IA control *u* (range 0–1). No external rules affect this matrix.

### Step 4 — Domain-Alignment Boost (Selection Only)

Pure semantics sometimes confuse structurally similar controls in different domains — for example, NIST CA-07 "Continuous Monitoring" scores slightly higher against T3.6 (operational monitoring logs) than against M6.2 (performance evaluation & improvement), because both contain the word *monitoring*. The domain-alignment boost corrects such near-ties.

A copy of `raw_sim` called `sel_sim` is created. For each (NIST family, UAE domain) pair in `DOMAIN_ALIGN`, the corresponding cells of `sel_sim` are multiplied by a boost factor (1.08 – 1.22×). **The boost is conditional**: it is applied to a UAE control only when its raw score is within `BOOST_WINDOW = 0.08` of the row's natural raw maximum. If the best raw match already has a comfortable lead, the domain knowledge does not override it — semantics take precedence.

This two-phase design prevents domain heuristics from forcing wrong matches onto controls where the embedding already gives a clear, correct answer.

### Step 5 — True-Mapping Decision

For each NIST control *n*:

1. **Select** the UAE candidate `best_u` = `argmax(sel_sim[n])` (domain-aware rank).
2. **Validate** using raw cosine scores (no boost artefacts):
   - `raw_sim[n, best_u] >= THRESH_ABS` (0.42) — minimum semantic similarity floor.
   - `raw_sim[n, best_u] - raw_sim[n, sec_u] >= MARGIN_ABS` (0.03) — the best must beat the second-best by a minimum gap, **or**
   - `raw_sim[n, best_u] >= BYPASS_SCORE` (0.52) — if the score is unambiguously strong, the margin requirement is waived.
3. Controls that fail validation receive `uae_ia_id = null` — they have **no true UAE IA mapping**.

The three-parameter gate (floor + margin + bypass) balances two risks:
- **False positives** (mapping unrelated controls): caught by the floor and margin.
- **False negatives** (rejecting valid matches because second-best is close): resolved by the bypass when the absolute score is strong.

---

## Outputs

### `NIST2.json`
The original NIST SP 800-53 OSCAL catalog with one new field injected into every control object:

```json
{
  "id": "ac-2",
  "title": "Account Management",
  ...
  "uae_ia_id": "T5.2.2"
}
```

`uae_ia_id` is the label of the UAE IA control this NIST control maps to, or `null` if no true mapping exists.

### `uae_to_nist_openai.json`
UAE-centric view: each UAE IA control lists all NIST controls mapped to it, sorted by descending cosine similarity score, with score and margin metadata.

---

## Results Summary

| Metric | Value |
|--------|-------|
| Embedding model | `text-embedding-3-large` (3,072-dim) |
| Total NIST controls | 1,196 |
| NIST controls mapped | 1,014 (84.8%) |
| NIST controls unmapped | 182 (15.2%) |
| UAE IA controls covered | 123 / 187 (65.8%) |
| Avg cosine similarity (mapped) | 0.597 |
| Min cosine similarity (mapped) | 0.433 |
| Max cosine similarity | 0.843 |
| Spot-check accuracy (27 known pairs) | 74% explicit / ~81% net of debatable expected values |

### Why 182 NIST Controls Are Unmapped

NIST SP 800-53 includes many highly specific enhancement controls (e.g., `AC-04(18)` "Security Attribute Binding", `CM-13` "Data Action Mapping") that address implementation details with no direct analogue in the UAE IA standard. Leaving these as `null` is correct — a forced mapping would be misleading.

### Why 64 UAE IA Controls Are Uncovered

UAE IA includes governance and organisational controls (principally the M1 and M2 domains — strategy, leadership, risk treatment) that have no NIST SP 800-53 equivalent. NIST 800-53 is technical-operational; UAE IA additionally mandates ISO 27001-style management system controls. These UAE controls correctly remain uncovered from the NIST direction.

---

## Determinism & Reproducibility

- Embeddings are cached after the first API call; subsequent runs load from disk.
- The similarity matrix, boost logic, and threshold logic are all pure NumPy/scikit-learn operations with no randomness.
- Re-running `openai_semantic_engine.py` with the same cache files produces identical `NIST2.json` and `uae_to_nist_openai.json` every time.

---

## Accuracy Rationale

| Signal layer | Purpose |
|---|---|
| `text-embedding-3-large` (3,072-dim) | Captures deep semantic meaning of control prose across domains |
| Hierarchical text template (family/domain + title + all parts) | Provides scope context so the model distinguishes "audit logging" from "performance monitoring" |
| Domain-alignment boost (conditional, ≤ 1.22×) | Resolves near-ties where structural synonyms (e.g., *monitoring*) appear in two different security domains |
| Three-gate true-mapping filter (floor + margin + bypass) | Rejects ambiguous and spurious matches while preserving confident low-margin assignments |
