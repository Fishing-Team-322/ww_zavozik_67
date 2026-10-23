"""Производственный календарь РФ (открытые данные xmlcalendar.ru).

В датасете кейса операции идут только в рабочие дни по этому календарю:
ни одной операции в праздники и выходные, зато есть операции в перенесённые
рабочие субботы. Поэтому:
  * в нерабочий день прогноз потока — ровно ноль;
  * признаки считаются в рабочих днях: после длинных выходных копится
    эквайринг, ЕНП «28-го» уходит на следующий рабочий день, зарплату
    платят в последний рабочий день до даты.

Файлы calendar_data/ru_<год>.json: в months[].days перечислены нерабочие дни;
«*» — сокращённый рабочий день (рабочий), «+» — перенесённый выходной.
Для лет без файла — обычная пятидневка.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA = Path(__file__).with_name("calendar_data")
# Диапазон таблицы; для лет без файла — пятидневка, вне диапазона — тоже.
START = np.datetime64("2000-01-01", "D")
END = np.datetime64("2060-12-31", "D")


@lru_cache(maxsize=1)
def _table() -> dict[str, np.ndarray]:
    days = np.arange(START, END + np.timedelta64(1, "D"))
    weekday = (days.astype("datetime64[D]").view("int64") - 4) % 7  # 0 = понедельник
    work = weekday < 5
    for f in sorted(DATA.glob("ru_*.json")):
        d = json.loads(f.read_text())
        year = d["year"]
        y0 = (np.datetime64(f"{year}-01-01") - START).astype(int)
        y1 = (np.datetime64(f"{year + 1}-01-01") - START).astype(int)
        work[y0:y1] = True
        for m in d["months"]:
            for tok in m["days"].split(","):
                tok = tok.strip()
                if not tok or tok.endswith("*"):
                    continue
                i = (np.datetime64(date(year, m["month"], int(tok.rstrip("+")))) - START).astype(int)
                work[i] = False

    n = len(days)
    # Сколько нерабочих дней подряд непосредственно перед днём.
    off_before = np.zeros(n, dtype=int)
    run = 0
    for i in range(n):
        off_before[i] = run
        run = 0 if work[i] else run + 1

    ds = days.astype(object)
    month_key = np.array([d.year * 12 + d.month for d in ds])
    dom = np.array([d.day for d in ds])
    # Номер рабочего дня в месяце и сколько рабочих дней до конца месяца.
    wd_of_month = np.zeros(n, dtype=int)
    wd_to_eom = np.zeros(n, dtype=int)
    for key in np.unique(month_key):
        idx = np.flatnonzero(month_key == key)
        c = np.cumsum(work[idx])
        wd_of_month[idx] = c
        wd_to_eom[idx] = c[-1] - c
    # Платёжные дни со сдвигом: ЕНП 28-го — первый рабочий день >= 28;
    # зарплата 10-го/25-го и аванс — последний рабочий день <= даты.
    tax_day = np.zeros(n, dtype=bool)
    pay10 = np.zeros(n, dtype=bool)
    pay25 = np.zeros(n, dtype=bool)
    for key in np.unique(month_key):
        idx = np.flatnonzero(month_key == key)
        w = idx[work[idx]]
        if not len(w):
            continue
        after28 = w[dom[w] >= 28]
        if len(after28):
            tax_day[after28[0]] = True
        for target, flag in ((10, pay10), (25, pay25)):
            before = w[dom[w] <= target]
            if len(before):
                flag[before[-1]] = True
    return {
        "work": work,
        "off_before": off_before,
        "wd_of_month": wd_of_month,
        "wd_to_eom": wd_to_eom,
        "tax_day": tax_day,
        "pay10": pay10,
        "pay25": pay25,
        "cum_work": np.concatenate([[0], np.cumsum(work)]),
    }


def _index(dates: np.ndarray) -> np.ndarray:
    """Индексы в таблице; даты вне диапазона сдвигаются на целое число недель
    внутрь (день недели сохраняется, праздников там нет)."""
    d = np.asarray(dates, dtype="datetime64[D]")
    i = (d - START).astype(int)
    n = int((END - START).astype(int)) + 1
    weeks = 7 * 52 * 5  # ~5 лет кратно неделе
    while (i < 0).any() or (i >= n).any():
        i = np.where(i < 0, i + weeks, np.where(i >= n, i - weeks, i))
    return i


def is_workday(dates) -> np.ndarray:
    return _table()["work"][_index(dates)]


def features(dates, origin) -> dict[str, np.ndarray]:
    """Календарные признаки целевых дней `dates` для прогноза от дня `origin`
    (скаляр или массив той же длины)."""
    t = _table()
    i = _index(dates)
    o = _index(np.broadcast_to(np.asarray(origin, dtype="datetime64[D]"), np.shape(i)))
    return {
        "is_workday": t["work"][i].astype(int),
        "off_before": np.minimum(t["off_before"][i], 12),
        "wd_of_month": t["wd_of_month"][i],
        "wd_to_eom": t["wd_to_eom"][i],
        "is_tax_day": t["tax_day"][i].astype(int),
        "is_pay10": t["pay10"][i].astype(int),
        "is_pay25": t["pay25"][i].astype(int),
        # Рабочих дней от точки старта до целевого дня включительно.
        "workdays_ahead": t["cum_work"][i + 1] - t["cum_work"][o + 1],
    }
