# Dynamic semantic categories and hierarchy

Active user requirement: discover **all** categories from vectors, with coarse
groups and subgroups. No seed category names, category labels, fixed K or
category-trained checkpoints. See `docs/CATEGORY_DISCOVERY_DESIGN.md` and
`ml/reports/classifier_v2.md`. Current result is **research**, not independently
validated accounting semantics.

Run from repository root; outputs are immutable, so use a fresh directory for
a genuinely new experiment. Never rerun a consumed final evaluation or use it
to adjust the fitted recipe.

```bash
# Optional environment, separate from the existing forecast server:
python3.12 -m venv ml/data/discovery_venv
ml/data/discovery_venv/bin/pip install -e 'ml[discovery,dev]'
# Existing local experiments used ml/data/chronos_venv, not the prod .venv.
```

The pinned base already exists locally at
`ml/data/classifier_v2/base/e5-small/614241f622f53c4eeff9890bdc4f31cfecc418b3`.
Its `base_source.json` binds every downloaded file and the MIT license.
Loading uses local files only; no operation text goes to an external API.

The following are the original commands, **already executed** with outputs
under `ml/data/category_discovery`. Inspect the results instead of duplicating:

```bash
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.corpus \
  --source cashflow_dataset_participants/all_operations.csv \
  --frozen ml/data/classifier_v2/prepared_disjoint_v3 \
  --out ml/data/category_discovery/corpus_v2
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.encoder \
  --corpus ml/data/category_discovery/corpus_v2 \
  --base ml/data/classifier_v2/base/e5-small/614241f622f53c4eeff9890bdc4f31cfecc418b3 \
  --out ml/data/category_discovery/e5_embeddings_v2 --device mps
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.experiment fit \
  --corpus ml/data/category_discovery/corpus_v2 --embeddings ml/data/category_discovery/e5_embeddings_v2 \
  --experiment ml/data/category_discovery/experiment_v1
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.experiment evaluate \
  --corpus ml/data/category_discovery/corpus_v2 --embeddings ml/data/category_discovery/e5_embeddings_v2 \
  --experiment ml/data/category_discovery/experiment_v1 --unlock-final
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.hierarchy \
  --inventory ml/data/category_discovery/experiment_v1/inventory \
  --out ml/data/category_discovery/experiment_v1/hierarchy_v2.json
```

`fit` reads train only. Reused frozen ownership was historically weak-label
stratified; the new corpus does not read labels or synthetic/augmented rows.
Actual tokenizer128input intersections are checked before embedding. Fits use
family medoids; row frequency does not create independent density.

`fit --parent EXISTING_INVENTORY` creates new categories only from genuine
outside/no-category residuals in a **new** discovery corpus. Ambiguous borders
are excluded, probable existing-category synonyms are not auto-added, and
existing IDs/centers remain unchanged. A no-op preserves the inventory version.
Hierarchy can be rebuilt for the new inventory. Reviewed split/merge/rename
requires a separate version and independent assessment.

Publication copies the exact base, fit_source as historical data, hierarchy,
model card and hashes. It never changes an existing release. Files inside
`fit_source` are not imported at inference.

```bash
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.release \
  --experiment ml/data/category_discovery/experiment_v1 \
  --hierarchy ml/data/category_discovery/experiment_v1/hierarchy_v2.json \
  --base ml/data/classifier_v2/base/e5-small/614241f622f53c4eeff9890bdc4f31cfecc418b3 \
  --model-root ml/models/classifiers --card ml/reports/classifier_v2.md
# Use the returned immutable model path:
PYTHONPATH=ml:ml/gen ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.server \
  --model /ABSOLUTE/PATH/TO/discovery-v1-HASH --listen 127.0.0.1:50054
```

The service runs CPU PyTorch in its own process, without LightGBM imports.
For Linux, an optional image can be built with
`docker build --build-arg ML_EXTRA=discovery -t zavozik-discovery ml`; mount the
entire release read-only and override the command to
`python -m zavozik_ml.category_discovery.server --model /models/RELEASE --listen 0.0.0.0:50054`.
Default image/entrypoint remain v1/forecast. This change was tested on native
macOS CPU; a Linux image build/deployment was not performed and needs a server smoke check.
`proto/categorize/v3/discovery.proto` exposes Assign/GetTaxonomy. IDs, order and
duplicates are preserved. Empty or weak input may be unassigned; inspect status
and candidates. Cosine/margin are geometry, **not** correctness probabilities.
GetTaxonomy contains direction roots, intermediate groups and leaves; each
assigned operation returns its path and coarse ID. Both taxonomy_version and
hierarchy_version must be persisted. Aggregate at one chosen level per view.
Internal-node company counts are unknown and omitted. Auxiliary channels/tags
are conservative weak text evidence, not learned/probabilistic outputs.

Independent review (already created120blind pairs; do not show the private key
to reviewers). Copy blind_pairs.jsonl to a separate reviewed file and fill
`judgment`: same/different/uncertain and `reviewer`. Do not modify pair inputs.
These pairs audit leaf-level economic coherence; hierarchy needs a separate
coarse-level assessment. No labels are prefilled or inferred from the clusters.

For a reviewer-friendly offline page, generate it with `review_ui --blind
PATH/blind_pairs.jsonl --out PATH/review.html`. The current page is already at
`ml/data/category_discovery/blind_review_v1/review.html`. Open it in a browser,
enter a reviewer identity, choose same/different/uncertain, then download JSONL.
The page makes no network requests and never embeds the private sampling key.
Browser-local progress is not a substitute for exporting the reviewed file.

```bash
PYTHONPATH=ml ml/data/chronos_venv/bin/python -m zavozik_ml.category_discovery.review score \
  --review ml/data/category_discovery/blind_review_v1 --judgments /path/to/reviewed.jsonl
cd ml
PYTHONPATH=.:gen .venv/bin/python -m pytest -q
PYTHONPATH=.:gen data/chronos_venv/bin/python -m pytest -q --ignore=tests/test_trx.py
```

Test fixtures with fabricated labels validate code only, never model quality.
The frozen final is internal data, not external human gold. Do not retrain on
its judgments and then reuse it as an independent test.
