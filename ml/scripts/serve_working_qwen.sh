#!/usr/bin/env bash
# Local research service. See the sealed release's model_card.json before use.
set -euo pipefail
QWEN_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
QWEN_PYTHON="${ML_QWEN_PYTHON:-python3}"
QWEN_MODEL="${ML_QWEN_MODEL:-$QWEN_REPO_ROOT/ml/data/category_discovery/working_qwen_v1/release_v4}"
export PYTHONPATH="$QWEN_REPO_ROOT/ml:$QWEN_REPO_ROOT/ml/gen${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
exec "$QWEN_PYTHON" -m zavozik_ml.category_discovery.working_server --model "$QWEN_MODEL" --listen "${ML_QWEN_LISTEN:-127.0.0.1:50054}" "$@"
