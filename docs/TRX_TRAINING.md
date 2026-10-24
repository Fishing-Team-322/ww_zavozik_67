# Обучение трансформера транзакций (TrxGPT)

Код — `ml/zavozik_ml/trx/` (описание модулей в `__init__.py`). Обучение идёт на
ПК с RTX 4060 Ti (8 ГБ) в WSL2 Ubuntu; управление — с Мака по SSH.

## Машина

| | |
|---|---|
| ОС | Windows + WSL2 Ubuntu 24.04 (дистрибутив по умолчанию — `Ubuntu`) |
| GPU | RTX 4060 Ti, 8 ГБ, драйвер с CUDA 13.5, bf16 поддерживается |
| RAM в WSL | 15 ГБ (половина от 32 ГБ по умолчанию) |
| Диск | `/home/denbay`, ~950 ГБ свободно — данные держать здесь, не в `/mnt/c` |
| Проект | `/home/denbay/zavozik` (код ML копируется с Мака через rsync) |
| Python | `~/zavozik/ml/.venv-train` (uv, torch с CUDA, numpy, pandas, pyarrow, pytest) |

Чтобы WSL видел больше памяти для подготовки MBD, в Windows создать
`C:\Users\denbay\.wslconfig`:

```ini
[wsl2]
memory=26GB
swap=16GB
autoProxy=false
```

и перезапустить WSL: `wsl --shutdown`. `autoProxy=false` убирает
предупреждение про localhost-прокси в выводе каждой команды. Предупреждение
про `automount.crossDistro` — лишняя строка в `/etc/wsl.conf` (удалить её
через `sudo nano /etc/wsl.conf`).

## Доступ с Мака

`~/.ssh/config` на Маке:

```
Host zavozik-pc
    HostName 192.168.1.68
    User denbay
    IdentityFile ~/.ssh/zavozik_pc
    IdentitiesOnly yes
    ServerAliveInterval 30
```

На ПК: OpenSSH Server (winget `Microsoft.OpenSSH.Preview`), вход только по
ключу (`PasswordAuthentication no` в `C:\ProgramData\ssh\sshd_config`, ключ в
`C:\ProgramData\ssh\administrators_authorized_keys`), оболочка SSH —
`C:\Windows\System32\bash.exe` (реестр `HKLM:\SOFTWARE\OpenSSH\DefaultShell`),
то есть сразу Ubuntu. Порт 22 открыт только в частной сети, наружу не пробрасывать.

Синхронизация кода с Мака:

```bash
rsync -az --delete --exclude __pycache__ ml/zavozik_ml ml/tests ml/eval ml/pyproject.toml zavozik-pc:/home/denbay/zavozik/ml/
```

Долгие задачи запускаются в `tmux`, чтобы переживать обрыв SSH и сон Мака:

```bash
ssh zavozik-pc 'tmux new -d -s train "cd ~/zavozik/ml && PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.train ... 2>&1 | tee runs/<имя>/stdout.log"'
ssh zavozik-pc 'tail -5 ~/zavozik/ml/runs/<имя>/log.csv; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv'
```

## Порядок работы

### 1. Данные

```bash
# кейс (на Маке уже подготовлен и скопирован): data/trx/case
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.prepare_case --out data/trx/case

# MBD-mini — сначала, чтобы увидеть схему, знак сумм и валюту (~2 ГБ архив)
# полный MBD — только транзакции (detail.tar.gz 38 ГБ, распаковать только detail/trx)
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.prepare_mbd --trx ~/data/mbd/detail/trx --out data/trx/mbd
```

### 2. Замер скорости (1% данных)

Короткий прогон, чтобы узнать операций/с и выбрать размер модели под 8 ГБ:

```bash
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.train --data data/trx/mbd --out runs/probe \
  --d-model 256 --layers 6 --seq-len 512 --batch 32 --max-steps 500 --eval-every 250
```

### 3. Предобучение на MBD

```bash
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.train --data data/trx/mbd --out runs/pretrain \
  --d-model 256 --layers 6 --seq-len 512 --batch 32 --accum 2 --lr 3e-4 --max-steps 200000 --workers 4
# продолжить после обрыва
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.train --resume runs/pretrain
```

### 4. Дообучение на кейсе

Только компании разработки и только до начала аудита (`eval/split_v2.json`,
`audit_start` = 2026-07-01); валидация — компании аудита до той же даты:

```bash
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.train --init runs/pretrain/best.pt \
  --data data/trx/case:development:2026-06-30 --val data/trx/case:audit:2026-06-30 \
  --out runs/finetune --lr 1e-4 --warmup 200 --max-steps 20000 --eval-every 500
```

### 5. Проверка прогноза

Компании аудита, точки старта с 2026-07-01, сравнение с seasonal naive:

```bash
PYTHONPATH=. .venv-train/bin/python -m zavozik_ml.trx.evaluate --model runs/finetune/best.pt \
  --roles audit --min-origin 2026-07-01 --paths 200 --out runs/finetune/eval.csv
```

Планка для сравнения — текущий прод-ансамбль (LightGBM + naive): WAPE остатка
~48% на 30 днях на новых компаниях (см. README «Качество прогноза»).

## Что уже проверено

- 6 тестов `ml/tests/test_trx.py` (формат шарда, обучение маленькой модели,
  генерация с календарём и лимитом операций в день, расширение словаря, контрольные точки).
- Пробное обучение на Mac (MPS), 6 минут, маленькая модель: валидационная
  потеря на компаниях аудита 4,70 → 4,61; на 7 точках старта WAPE 15% / 23% /
  69% (7 / 14 / 30 дней) против 19% / 33% / 52% у naive.

## Следующие шаги

- События (счета, договоры, налоги, ручной ввод) — токены-планы перед прогнозом
  и голова «операция реализует событие».
- Эмбеддинги назначений от классификатора v2 как вход.
- Персональный адаптер компании (LoRA) поверх обученной модели.
- KV-кеш в генерации — сейчас каждый шаг пересчитывает весь контекст.
