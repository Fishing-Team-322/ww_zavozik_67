"""Генерация будущих операций и дневных потоков из TrxGPT.

По истории компании до дня прогноза модель пошагово сэмплирует следующие
операции для n_paths вариантов будущего параллельно: через сколько дней →
направление → тип → сумма. Ограничения:
  * операция не раньше дня после прогноза и не позже горизонта;
  * если в истории компании нет операций в нерабочие дни, нерабочие дни по
    производственному календарю запрещены (как в данных кейса);
  * тип — только из типов того же источника (для кейса — наши категории),
    направление «неизвестно» не сэмплируется.

Результат — дневные приходы и расходы бизнеса по каждому пути (внутренние
переводы владельца отдельно) — то же, что отдаёт ML-сервис для Go.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from zavozik_ml import calendar as cal

from .dataset import INPUT_FIELDS, SOURCE_IDS
from .model import TrxGPT
from .schema import (
    DELTA_FAR,
    DIR_IN,
    DIR_UNKNOWN,
    INTERNAL_TYPES,
    MAX_DELTA,
    TypeVocab,
    amount_bin,
    amount_from_bin,
    calendar_fields,
    log_amount,
)


@dataclass
class GeneratedPaths:
    origin_day: int  # день прогноза (от 1970-01-01); горизонт — дни origin+1..origin+H
    business_in: np.ndarray  # (paths, H)
    business_out: np.ndarray  # (paths, H)
    internal_net: np.ndarray  # (paths, H), со знаком
    n_ops: np.ndarray  # (paths,) сколько операций сгенерировано


def context_tokens(tokens: dict[str, np.ndarray], remap: np.ndarray | None, source: str) -> dict[str, np.ndarray]:
    """Токены истории из шарда → входы модели (типы в словаре модели)."""
    # В шарде поля компактные (int8/int16); эмбеддингам нужны int64.
    out = {k: np.asarray(tokens[k]).astype(np.float32 if k == "log_amount" else np.int64) for k in INPUT_FIELDS}
    if remap is not None:
        out["type"] = remap[out["type"]]
    out["src"] = np.full(len(out["delta"]), SOURCE_IDS.get(source, 1), dtype=np.int64)
    out["day"] = np.asarray(tokens["day"], dtype=np.int64)
    return out


def _sample(logits: torch.Tensor, gen: torch.Generator, temperature: float) -> torch.Tensor:
    probs = torch.softmax(logits.float() / temperature, dim=-1)
    return torch.multinomial(probs, 1, generator=gen).squeeze(-1)


@torch.no_grad()
def generate(model: TrxGPT, context: dict[str, np.ndarray], vocab: TypeVocab, origin_day: int, horizon: int,
             n_paths: int, source: str = "case", temperature: float = 1.0, seed: int = 0,
             max_ops_per_day: int = 40, device: torch.device | str = "cpu") -> GeneratedPaths:
    if len(context["delta"]) == 0:
        raise ValueError("пустая история: нечего продолжать")
    device = torch.device(device)
    model.eval()
    gen = torch.Generator(device="cpu").manual_seed(seed)
    rng = np.random.default_rng(seed)
    max_len = model.cfg.max_len

    # Нерабочие дни запрещены, только если в истории их не было (свойство источника).
    hist_days = context["day"]
    use_calendar = not bool((~cal.is_workday(hist_days.astype("datetime64[D]"))).any())
    allowed_types = torch.tensor([i for i in vocab.ids_with_prefix(f"{source}:")] or list(range(2, len(vocab))))
    type_mask = torch.full((len(vocab),), float("-inf"))
    type_mask[allowed_types] = 0.0
    internal = np.array([n in INTERNAL_TYPES for n in vocab.names])

    # Состояние: последовательность каждого пути (общая история + сгенерированное).
    seq = {k: torch.as_tensor(np.asarray(v)[-(max_len - 1):]).unsqueeze(0).repeat(n_paths, *([1] * (np.ndim(v)))) for k, v in context.items()
           if k != "day"}
    last_day = np.full(n_paths, int(hist_days[-1]), dtype=np.int64)
    # Лимит операций в день — по самой компании (1,5 × максимум в истории, не меньше 3):
    # иначе в последний день горизонта модель может бесконечно добавлять операции в тот же день.
    per_day = np.unique(hist_days, return_counts=True)[1]
    day_cap = int(min(max_ops_per_day, max(3, np.ceil(1.5 * per_day.max()))))
    today_count = np.full(n_paths, int(per_day[-1]), dtype=np.int64)
    active = np.ones(n_paths, dtype=bool)
    b_in = np.zeros((n_paths, horizon))
    b_out = np.zeros((n_paths, horizon))
    i_net = np.zeros((n_paths, horizon))
    n_ops = np.zeros(n_paths, dtype=np.int64)
    end_day = origin_day + horizon

    for _ in range(horizon * max_ops_per_day):
        if not active.any():
            break
        batch = {f"x_{k}": v[:, -max_len:].to(device) for k, v in seq.items()}
        h = model.encode(batch)[:, -1].float().cpu()

        # 1. Через сколько дней: день после прогноза, в пределах горизонта, рабочий.
        cand = last_day[:, None] + np.arange(MAX_DELTA + 1)[None, :]  # (paths, 31)
        ok = (cand > origin_day) & (cand <= end_day)
        if use_calendar:
            ok &= cal.is_workday(cand.astype("datetime64[D]"))
        ok[:, 0] &= today_count < day_cap  # лимит операций в текущий день набран — только следующие дни
        mask = np.full((n_paths, DELTA_FAR + 1), -np.inf, dtype=np.float32)
        mask[:, : MAX_DELTA + 1][ok] = 0.0
        mask[:, DELTA_FAR] = 0.0  # «до конца горизонта ничего» — всегда можно
        ld = model.logits_delta(h.to(device)).float().cpu() + torch.from_numpy(mask)
        delta = _sample(ld, gen, temperature).numpy()
        done = (delta == DELTA_FAR) | ~active
        day = last_day + np.where(done, 0, delta)
        active &= ~done
        if not active.any():
            break

        # 2–4. Направление, тип, сумма — с учётом дня и его календаря.
        c = calendar_fields(day)
        dev = lambda a: torch.as_tensor(a).to(device)
        lr, h_dir = model.logits_dir(h.to(device), dev(np.minimum(delta, DELTA_FAR)), dev(c["weekday"]), dev(c["dom"]),
                                     dev(c["month"]), dev(c["off_before"]), dev(c["flags"]))
        lr = lr.float().cpu()
        lr[:, DIR_UNKNOWN] = float("-inf")
        direction = _sample(lr, gen, temperature)
        lt, h_type = model.logits_type(h_dir, direction.to(device))
        typ = _sample(lt.float().cpu() + type_mask, gen, temperature)
        la = model.logits_amount(h_type, typ.to(device)).float().cpu()
        abin = _sample(la, gen, temperature).numpy()
        amount = amount_from_bin(abin, rng)

        # Записать операцию в дневные потоки активных путей.
        idx = np.flatnonzero(active)
        d_off = day[idx] - origin_day - 1
        dirs = direction.numpy()[idx]
        types = typ.numpy()[idx]
        amt = amount[idx]
        is_int = internal[types]
        sign = np.where(dirs == DIR_IN, 1.0, -1.0)
        np.add.at(i_net, (idx[is_int], d_off[is_int]), (sign * amt)[is_int])
        bi = ~is_int & (dirs == DIR_IN)
        bo = ~is_int & (dirs != DIR_IN)
        np.add.at(b_in, (idx[bi], d_off[bi]), amt[bi])
        np.add.at(b_out, (idx[bo], d_off[bo]), amt[bo])
        n_ops[idx] += 1

        # Дописать сгенерированный токен (у завершённых путей — повтор, он не учитывается).
        new = {
            "delta": torch.as_tensor(np.minimum(delta, DELTA_FAR)), "dir": direction, "type": typ,
            "amount_bin": torch.as_tensor(amount_bin(amount)), "log_amount": torch.as_tensor(log_amount(amount)),
            "weekday": torch.as_tensor(c["weekday"]), "dom": torch.as_tensor(c["dom"]), "month": torch.as_tensor(c["month"]),
            "off_before": torch.as_tensor(c["off_before"]), "flags": torch.as_tensor(c["flags"]),
            "src": seq["src"][:, -1],
        }
        for k, v in new.items():
            v = v.to(seq[k].dtype)
            seq[k] = torch.cat([seq[k], v.unsqueeze(1)], dim=1)[:, -max_len:]
        today_count = np.where(active, np.where(day == last_day, today_count + 1, 1), today_count)
        last_day = np.where(active, day, last_day)

    return GeneratedPaths(origin_day=origin_day, business_in=b_in, business_out=b_out, internal_net=i_net, n_ops=n_ops)
