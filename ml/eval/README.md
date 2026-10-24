# Оценка качества

`make backtest` (или `make backtest ML=localhost:50051` через ML-сервис)
пишет `ml/data/backtest.csv`: company_id, as_of, h, model, low_confidence,
actual, p10, p50, p90. Здесь — ноутбуки/скрипты с метриками (MAE/WAPE по
горизонтам, покрытие коридора, метрики по разрывам) и графиками для слайдов.
