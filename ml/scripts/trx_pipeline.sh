#!/usr/bin/env bash
# Полный прогон TrxGPT на ПК (WSL Ubuntu), по этапам, с остановкой при любой ошибке.
#
#   bash ~/zavozik/ml/scripts/trx_pipeline.sh          # все этапы с первого
#   bash ~/zavozik/ml/scripts/trx_pipeline.sh 5        # начать с этапа 5
#
# Запускать внутри tmux, чтобы закрытие окна не убило обучение:
#   tmux new -s trx      (отсоединиться: Ctrl+B, затем D;  вернуться: tmux attach -t trx)
#
# Этапы:
#   1. видеокарта и PyTorch
#   2. тесты трансформера
#   3. ожидание подготовки шардов MBD (если ещё идёт)
#   4. проверка данных: все шарды MBD и кейса (жёсткие проверки + отчёт; ошибка — стоп)
#   5. обучение на малых данных: кейс, 300 шагов — потеря должна падать
#   6. проба на MBD: 500 шагов — скорость и падение валидационной потери
#   7. полное предобучение на MBD
#   8. дообучение на кейсе (компании разработки до 2026-06-30)
#   9. проверка прогноза на компаниях аудита против naive
set -euo pipefail

ROOT=/home/denbay/zavozik/ml
SHARDS=/mnt/d/mbd/shards
PY="$ROOT/.venv-train/bin/python"
FROM=${1:-1}
cd "$ROOT"
export PYTHONPATH=.

TRAIN_PARTS="--data $SHARDS/part_0 --data $SHARDS/part_1 --data $SHARDS/part_2 --data $SHARDS/part_3 --data $SHARDS/part_4"
VAL_PART="--val $SHARDS/part_5"   # отдельные клиенты: модель их не видит при обучении

stage() { echo; echo "================ Этап $1: $2 ================"; }
run_stage() { [ "$FROM" -le "$1" ]; }
fail() { echo; echo "ОСТАНОВКА: $1"; exit 1; }

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

if run_stage 1; then
  stage 1 "видеокарта и PyTorch"
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv
  "$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA не видна'; print('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0), '| bf16', torch.cuda.is_bf16_supported())"
fi

if run_stage 2; then
  stage 2 "тесты трансформера"
  "$PY" -m pytest tests/test_trx.py -q || fail "тесты не прошли"
fi

if run_stage 3; then
  stage 3 "подготовка шардов MBD"
  while tmux has-session -t prepare 2>/dev/null && ! grep -q PREPARE_DONE /mnt/d/mbd/shards_prepare.log 2>/dev/null; do
    echo "  подготовка ещё идёт: записано $(du -sh $SHARDS | cut -f1) из ~30 ГБ ($(date +%H:%M))"
    sleep 60
  done
  grep -q PREPARE_DONE /mnt/d/mbd/shards_prepare.log || fail "подготовка не дошла до конца — см. /mnt/d/mbd/shards/part_*.log"
  grep -h "^MBD:" $SHARDS/part_*.log | grep -v "файлов"
fi

if run_stage 4; then
  stage 4 "проверка данных"
  "$PY" -m zavozik_ml.trx.validate $SHARDS/part_0 $SHARDS/part_1 $SHARDS/part_2 $SHARDS/part_3 $SHARDS/part_4 $SHARDS/part_5 \
    --expect-tokens 947899612 || fail "данные MBD не прошли проверку — обучать нельзя"
  "$PY" -m zavozik_ml.trx.validate data/trx/case --expect-tokens 222420 || fail "данные кейса не прошли проверку"
fi

if run_stage 5; then
  stage 5 "обучение на малых данных (кейс)"
  rm -rf runs/smoke-case
  "$PY" -m zavozik_ml.trx.train --data data/trx/case:development:2026-06-30 --val data/trx/case:audit:2026-06-30 \
    --out runs/smoke-case --d-model 128 --layers 4 --heads 4 --d-ff 512 --seq-len 256 --batch 32 \
    --lr 1e-3 --warmup 50 --max-steps 300 --eval-every 100 --val-windows 128 --workers 4
  val_dropped runs/smoke-case/log.csv || fail "на малых данных потеря не падает"
fi

if run_stage 6; then
  stage 6 "проба на MBD: скорость и обучаемость"
  rm -rf runs/probe-mbd
  "$PY" -m zavozik_ml.trx.train $TRAIN_PARTS $VAL_PART --out runs/probe-mbd \
    --d-model 256 --layers 6 --heads 8 --d-ff 1024 --seq-len 512 --batch 32 \
    --lr 3e-4 --warmup 100 --max-steps 500 --eval-every 250 --val-windows 256 --workers 6
  val_dropped runs/probe-mbd/log.csv || fail "на MBD потеря не падает"
  echo "скорость (операций/с) на последних шагах:"; tail -3 runs/probe-mbd/log.csv | cut -d, -f1,13
fi

if run_stage 7; then
  stage 7 "полное предобучение на MBD"
  echo "~2 эпохи (до 100 000 шагов), проверка на отдельных клиентах каждые 2000 шагов,"
  echo "ранняя остановка после 5 проверок без улучшения, контрольная точка каждые 20 мин."
  echo "Прервать: Ctrl+C. Продолжить после обрыва: этот же скрипт с этапа 7 (продолжит с last.pt)."
  if [ -f runs/pretrain/last.pt ]; then
    "$PY" -m zavozik_ml.trx.train --resume runs/pretrain
  else
    "$PY" -m zavozik_ml.trx.train $TRAIN_PARTS $VAL_PART --out runs/pretrain \
      --d-model 256 --layers 6 --heads 8 --d-ff 1024 --seq-len 512 --batch 32 --accum 2 \
      --lr 3e-4 --warmup 2000 --max-steps 100000 --eval-every 2000 --val-windows 1024 \
      --patience 5 --ckpt-minutes 20 --workers 6
  fi
  [ -f runs/pretrain/best.pt ] || fail "нет runs/pretrain/best.pt"
fi

if run_stage 8; then
  stage 8 "дообучение на кейсе"
  "$PY" -m zavozik_ml.trx.train --init runs/pretrain/best.pt \
    --data data/trx/case:development:2026-06-30 --val data/trx/case:audit:2026-06-30 \
    --out runs/finetune --seq-len 512 --batch 32 --lr 1e-4 --warmup 200 --max-steps 20000 \
    --eval-every 500 --val-windows 256 --patience 6 --workers 4
fi

if run_stage 9; then
  stage 9 "проверка прогноза на компаниях аудита"
  "$PY" -m zavozik_ml.trx.evaluate --model runs/finetune/best.pt --roles audit --min-origin 2026-07-01 \
    --paths 200 --out runs/finetune/eval.csv
  echo
  echo "Планка прод-ансамбля (LightGBM + naive): WAPE остатка ~48% на 30 днях на новых компаниях."
fi

echo; echo "Готово."
