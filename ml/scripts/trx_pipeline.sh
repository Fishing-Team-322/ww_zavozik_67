#!/usr/bin/env bash
# Полный прогон TrxGPT v2 на ПК (WSL Ubuntu), по этапам, с остановкой при любой ошибке.
#
#   bash ~/zavozik/ml/scripts/trx_pipeline.sh          # все этапы с первого
#   bash ~/zavozik/ml/scripts/trx_pipeline.sh 5        # начать с этапа 5
#
# Запускать внутри tmux, чтобы закрытие окна не убило обучение:
#   tmux new -s trx      (отсоединиться: Ctrl+B, затем D;  вернуться: tmux attach -t trx)
#
# После выключения ПК — тот же скрипт с того же этапа: подбор (Optuna, study.db)
# и предобучение (last.pt) продолжаются с места остановки, а не с нуля.
#
# Этапы:
#   1. видеокарта, PyTorch, Optuna (ставится, если нет)
#   2. тесты трансформера
#   3. обучение на малых данных: кейс, 300 шагов — потеря должна падать
#   4. подбор гиперпараметров предобучения (Optuna): размер модели, шаг, регуляризация
#   5. полное предобучение на MBD с лучшими параметрами
#   6. подбор гиперпараметров дообучения (Optuna) на компаниях разработки:
#      80% компаний — обучение, 20% — проверка. Аудит не трогаем.
#   7. итоговое дообучение на всех компаниях разработки с лучшими параметрами
#   8. проверка прогноза на компаниях аудита против naive (единственный раз, когда видим аудит)
#
# Сколько ждать (RTX 4060 Ti): этап 4 ~6 ч, этап 5 ~4–8 ч, этап 6 ~3 ч, остальное — минуты.
# Всё меняется переменными ниже, например:  PRE_TOKENS=1e9 bash trx_pipeline.sh 5
set -euo pipefail
set -f  # без подстановки имён файлов: в путях источников есть [0-80]

ROOT=/home/denbay/zavozik/ml
SHARDS=/mnt/d/mbd/shards
PY="$ROOT/.venv-train/bin/python"
FROM=${1:-1}

TUNE_PRE_TRIALS=${TUNE_PRE_TRIALS:-24}     # испытаний подбора предобучения
TUNE_PRE_HOURS=${TUNE_PRE_HOURS:-6}        # ...но не дольше
TUNE_PRE_TOKENS=${TUNE_PRE_TOKENS:-1.5e8}  # операций на испытание
PRE_TOKENS=${PRE_TOKENS:-2e9}              # полное предобучение: ~2 эпохи MBD
TUNE_FT_TRIALS=${TUNE_FT_TRIALS:-40}
TUNE_FT_HOURS=${TUNE_FT_HOURS:-3}
TUNE_FT_STEPS=${TUNE_FT_STEPS:-3000}
CUTOFF=2026-06-30                          # кейс: данные до начала аудита

cd "$ROOT"
export PYTHONPATH=.

TRAIN_PARTS="--data $SHARDS/part_0 --data $SHARDS/part_1 --data $SHARDS/part_2 --data $SHARDS/part_3 --data $SHARDS/part_4"
VAL_PART="--val $SHARDS/part_5"   # отдельные клиенты: модель их не видит при обучении
CASE=data/trx/case
FT_TRAIN="--data $CASE:development[0-80]:$CUTOFF"
FT_VAL="--val $CASE:development[80-100]:$CUTOFF"

stage() { echo; echo "================ Этап $1: $2 ($(date +%H:%M)) ================"; }
run_stage() { [ "$FROM" -le "$1" ]; }
fail() { echo; echo "ОСТАНОВКА: $1"; exit 1; }
need() { [ -f "$1" ] || fail "нет $1 — сначала предыдущий этап"; }

# Проверка, что потеря упала: последняя валидационная потеря в log.csv меньше первой.
val_dropped() {
  "$PY" - "$1" <<'EOF'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["val_loss"]]
if len(rows) < 2:
    sys.exit("мало точек валидации")
a, b = float(rows[0]["val_loss"]), float(rows[-1]["val_loss"])
print(f"валидационная потеря: {a:.3f} -> {b:.3f}")
sys.exit(0 if b < a else 1)
EOF
}

# torch.compile ускоряет в 1,3–2 раза, но нужен Triton; без него — обычный режим.
COMPILE=""
if "$PY" -c "import triton" 2>/dev/null; then COMPILE="--compile"; fi

if run_stage 1; then
  stage 1 "видеокарта, PyTorch, Optuna"
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv
  "$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA не видна'; print('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0), '| bf16', torch.cuda.is_bf16_supported())"
  if ! "$PY" -c "import optuna" 2>/dev/null; then
    echo "ставлю Optuna..."
    if command -v uv >/dev/null; then uv pip install --python "$PY" optuna; else "$PY" -m pip install optuna; fi
  fi
  "$PY" -c "import optuna; print('optuna', optuna.__version__)"
  echo "torch.compile: ${COMPILE:-нет Triton, без компиляции}"
fi

if run_stage 2; then
  stage 2 "тесты трансформера"
  "$PY" -m pytest tests/test_trx.py -q || fail "тесты не прошли"
fi

if run_stage 3; then
  stage 3 "обучение на малых данных (кейс)"
  rm -rf runs/smoke-case
  "$PY" -m zavozik_ml.trx.train $FT_TRAIN $FT_VAL \
    --out runs/smoke-case --d-model 128 --layers 4 --heads 4 --d-ff 512 --seq-len 256 --batch 32 \
    --lr 1e-3 --warmup 50 --max-steps 300 --eval-every 100 --val-windows 128 --workers 4
  val_dropped runs/smoke-case/log.csv || fail "на малых данных потеря не падает"
fi

if run_stage 4; then
  stage 4 "подбор гиперпараметров предобучения (Optuna)"
  echo "$TUNE_PRE_TRIALS испытаний по $TUNE_PRE_TOKENS операций, не дольше $TUNE_PRE_HOURS ч; слабые обрываются рано."
  "$PY" -m zavozik_ml.trx.tune pretrain --out runs/tune-pretrain --trials "$TUNE_PRE_TRIALS" \
    --hours "$TUNE_PRE_HOURS" --trial-tokens "$TUNE_PRE_TOKENS" -- \
    $TRAIN_PARTS $VAL_PART --seq-len 512 --val-windows 512 --workers 6
  need runs/tune-pretrain/best_args.txt
fi

if run_stage 5; then
  stage 5 "полное предобучение на MBD"
  pretrain() {  # $1 — флаг компиляции или пусто
    if [ -f runs/pretrain-v2/last.pt ]; then
      echo "продолжаю с runs/pretrain-v2/last.pt"
      "$PY" -m zavozik_ml.trx.train --resume runs/pretrain-v2 $1
    else
      need runs/tune-pretrain/best_args.txt
      BEST=$(cat runs/tune-pretrain/best_args.txt)
      echo "лучшие параметры подбора: $BEST"
      "$PY" -m zavozik_ml.trx.train $TRAIN_PARTS $VAL_PART --out runs/pretrain-v2 $BEST \
        --seq-len 512 --token-budget "$PRE_TOKENS" --eval-every 2000 --val-windows 1024 \
        --patience 8 --ckpt-minutes 15 --workers 6 $1
    fi
  }
  pretrain "$COMPILE" || { [ -n "$COMPILE" ] && echo "с torch.compile упало — продолжаю без него" && pretrain ""; }
  need runs/pretrain-v2/best.pt
fi

if run_stage 6; then
  stage 6 "подбор гиперпараметров дообучения (Optuna)"
  need runs/pretrain-v2/best.pt
  "$PY" -m zavozik_ml.trx.tune finetune --out runs/tune-finetune --trials "$TUNE_FT_TRIALS" \
    --hours "$TUNE_FT_HOURS" --trial-steps "$TUNE_FT_STEPS" --evals 10 --replay "$SHARDS/part_0" -- \
    --init runs/pretrain-v2/best.pt $FT_TRAIN $FT_VAL --seq-len 512 --batch 32 --val-windows 256 --workers 4
  need runs/tune-finetune/best_args.txt
fi

if run_stage 7; then
  stage 7 "итоговое дообучение на всех компаниях разработки"
  need runs/tune-finetune/best.json
  BEST=$(cat runs/tune-finetune/best_args.txt)
  # Шагов — как у лучшего испытания до его лучшей точки, с поправкой на 25% больше данных.
  STEPS=$("$PY" -c "import json; b = json.load(open('runs/tune-finetune/best.json')); print(int(b.get('best_step', b['max_steps']) * 1.25))")
  echo "лучшие параметры: $BEST | шагов: $STEPS"
  rm -rf runs/finetune-v2
  # Валидация здесь — на тех же компаниях, что в обучении: только для глаз, не для выбора.
  "$PY" -m zavozik_ml.trx.train --init runs/pretrain-v2/best.pt --data "$CASE:development:$CUTOFF" $FT_VAL \
    --out runs/finetune-v2 $BEST --seq-len 512 --batch 32 --max-steps "$STEPS" --eval-every 250 \
    --val-windows 256 --workers 4
  need runs/finetune-v2/final.pt
fi

if run_stage 8; then
  stage 8 "проверка прогноза на компаниях аудита"
  need runs/finetune-v2/final.pt
  "$PY" -m zavozik_ml.trx.evaluate --model runs/finetune-v2/final.pt --roles audit --min-origin 2026-07-01 \
    --paths 200 --out runs/finetune-v2/eval.csv
  echo
  echo "Планка прод-ансамбля (LightGBM + naive): WAPE остатка ~48% на 30 днях на новых компаниях."
fi

echo; echo "Готово. Итоговая модель: $ROOT/runs/finetune-v2/final.pt"
