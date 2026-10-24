"""TrxGPT — декодер-трансформер на последовательностях операций.

Вход на позиции t — сумма эмбеддингов полей операции t (дни после
предыдущей, направление, тип, интервал суммы, точный логарифм суммы,
календарь дня, источник данных) + позиция.

Предсказание операции t+1 — цепочкой голов, каждая видит ответы предыдущих:
  1. через сколько дней (delta);
  2. направление — уже зная день и его календарь (рабочий ли, 28-е, зарплата);
  3. тип — зная день и направление;
  4. интервал суммы — зная день, направление и тип.
При обучении в цепочку подаются истинные значения (teacher forcing), при
генерации — сэмплированные. Так модель учит совместное распределение
«когда / что / сколько», а не независимые маргиналы.

Точки расширения: эмбеддинг события-плана и персональный адаптер компании
добавляются как ещё одно слагаемое входа (см. docs/TRX_TRAINING.md).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .dataset import IGNORE
from .schema import MAX_OFF_BEFORE, N_AMOUNT, N_DELTA, N_DIR


@dataclass
class TrxConfig:
    n_types: int
    d_model: int = 256
    n_layers: int = 6
    n_heads: int = 8
    d_ff: int = 1024
    max_len: int = 512
    dropout: float = 0.1
    n_sources: int = 2
    loss_weights: tuple[float, float, float, float] = (1.0, 0.5, 1.0, 1.0)  # delta, dir, type, amount

    def to_dict(self) -> dict:
        return asdict(self)


class CalendarEmbedding(nn.Module):
    """Календарь дня: день недели, число, месяц, выходные подряд + флаги."""

    def __init__(self, d: int):
        super().__init__()
        self.weekday = nn.Embedding(7, d)
        self.dom = nn.Embedding(31, d)
        self.month = nn.Embedding(12, d)
        self.off_before = nn.Embedding(MAX_OFF_BEFORE + 1, d)
        self.flags = nn.Linear(4, d, bias=False)

    def forward(self, weekday, dom, month, off_before, flags):
        return (self.weekday(weekday) + self.dom(dom) + self.month(month)
                + self.off_before(off_before) + self.flags(flags.float()))


class Block(nn.Module):
    def __init__(self, cfg: TrxConfig):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.ln1 = nn.LayerNorm(cfg.d_model)
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model)
        self.ln2 = nn.LayerNorm(cfg.d_model)
        self.ff = nn.Sequential(nn.Linear(cfg.d_model, cfg.d_ff), nn.GELU(), nn.Linear(cfg.d_ff, cfg.d_model))
        self.drop = nn.Dropout(cfg.dropout)
        self.attn_dropout = cfg.dropout

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, n, d = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(b, n, 3, self.n_heads, d // self.n_heads).unbind(2)
        q, k, v = (t.transpose(1, 2) for t in (q, k, v))
        # Встроенное быстрое внимание PyTorch (Flash/Memory-efficient на CUDA).
        a = F.scaled_dot_product_attention(q, k, v, is_causal=True,
                                           dropout_p=self.attn_dropout if self.training else 0.0)
        x = x + self.drop(self.proj(a.transpose(1, 2).reshape(b, n, d)))
        return x + self.drop(self.ff(self.ln2(x)))


class TrxGPT(nn.Module):
    def __init__(self, cfg: TrxConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model
        # Вход: поля текущей операции.
        self.delta_emb = nn.Embedding(N_DELTA, d)
        self.dir_emb = nn.Embedding(N_DIR, d)
        self.type_emb = nn.Embedding(cfg.n_types, d)
        self.amount_emb = nn.Embedding(N_AMOUNT, d)
        self.log_amount_emb = nn.Linear(1, d)
        self.calendar_emb = CalendarEmbedding(d)
        self.source_emb = nn.Embedding(cfg.n_sources, d)
        self.pos_emb = nn.Embedding(cfg.max_len, d)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.ln = nn.LayerNorm(d)
        # Цепочка голов для следующей операции; у каждой — свои эмбеддинги условий.
        self.head_delta = nn.Linear(d, N_DELTA)
        self.cond_delta = nn.Embedding(N_DELTA, d)
        self.cond_calendar = CalendarEmbedding(d)
        self.head_dir = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, N_DIR))
        self.cond_dir = nn.Embedding(N_DIR, d)
        self.head_type = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, cfg.n_types))
        self.cond_type = nn.Embedding(cfg.n_types, d)
        self.head_amount = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, N_AMOUNT))
        self.apply(self._init)

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    # --- общий ствол ---

    def encode(self, b: dict[str, torch.Tensor]) -> torch.Tensor:
        """Скрытые состояния [batch, n, d] для входных операций."""
        n = b["x_delta"].shape[1]
        if n > self.cfg.max_len:
            raise ValueError(f"длина {n} больше max_len {self.cfg.max_len}")
        pos = torch.arange(n, device=b["x_delta"].device)
        x = (self.delta_emb(b["x_delta"]) + self.dir_emb(b["x_dir"]) + self.type_emb(b["x_type"])
             + self.amount_emb(b["x_amount_bin"]) + self.log_amount_emb(b["x_log_amount"].unsqueeze(-1))
             + self.calendar_emb(b["x_weekday"], b["x_dom"], b["x_month"], b["x_off_before"], b["x_flags"])
             + self.source_emb(b["x_src"]) + self.pos_emb(pos))
        x = self.drop(x)
        for blk in self.blocks:
            x = blk(x)
        return self.ln(x)

    # --- цепочка голов ---

    def logits_delta(self, h: torch.Tensor) -> torch.Tensor:
        return self.head_delta(h)

    def logits_dir(self, h, delta, weekday, dom, month, off_before, flags) -> torch.Tensor:
        h = h + self.cond_delta(delta) + self.cond_calendar(weekday, dom, month, off_before, flags)
        return self.head_dir(h), h

    def logits_type(self, h_dir: torch.Tensor, direction: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = h_dir + self.cond_dir(direction)
        return self.head_type(h), h

    def logits_amount(self, h_type: torch.Tensor, typ: torch.Tensor) -> torch.Tensor:
        return self.head_amount(h_type + self.cond_type(typ))

    def forward(self, b: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Потери по каждому полю (teacher forcing) и их взвешенная сумма."""
        h = self.encode(b)
        safe = lambda t: t.clamp_min(0)  # IGNORE (−100) в условиях заменяем на 0, потеря его игнорирует
        ld = self.logits_delta(h)
        lr, h_dir = self.logits_dir(h, safe(b["y_delta"]), b["y_weekday"], b["y_dom"], b["y_month"],
                                    b["y_off_before"], b["y_flags"])
        lt, h_type = self.logits_type(h_dir, safe(b["y_dir"]))
        la = self.logits_amount(h_type, safe(b["y_type"]))
        losses = {
            "delta": F.cross_entropy(ld.flatten(0, 1).float(), b["y_delta"].flatten(), ignore_index=IGNORE),
            "dir": _ce(lr, b["y_dir"]),
            "type": F.cross_entropy(lt.flatten(0, 1).float(), b["y_type"].flatten(), ignore_index=IGNORE),
            "amount": F.cross_entropy(la.flatten(0, 1).float(), b["y_amount_bin"].flatten(), ignore_index=IGNORE),
        }
        w = self.cfg.loss_weights
        losses["loss"] = w[0] * losses["delta"] + w[1] * losses["dir"] + w[2] * losses["type"] + w[3] * losses["amount"]
        return losses

    # --- дообучение с расширенным словарём ---

    @torch.no_grad()
    def resize_types(self, n_types: int) -> None:
        """Увеличить словарь типов: старые строки сохраняются, новые — случайные."""
        if n_types <= self.cfg.n_types:
            return
        for name in ("type_emb", "cond_type"):
            old: nn.Embedding = getattr(self, name)
            new = nn.Embedding(n_types, old.embedding_dim).to(old.weight.device)
            nn.init.normal_(new.weight, std=0.02)
            new.weight[: old.num_embeddings] = old.weight
            setattr(self, name, new)
        old_head: nn.Linear = self.head_type[-1]
        new_head = nn.Linear(old_head.in_features, n_types).to(old_head.weight.device)
        nn.init.normal_(new_head.weight, std=0.02)
        nn.init.zeros_(new_head.bias)
        new_head.weight[: old_head.out_features] = old_head.weight
        new_head.bias[: old_head.out_features] = old_head.bias
        self.head_type[-1] = new_head
        self.cfg.n_types = n_types


def _ce(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Кросс-энтропия, устойчивая к батчу без единой размеченной позиции."""
    t = target.flatten()
    if not (t != IGNORE).any():
        return logits.sum() * 0.0
    return F.cross_entropy(logits.flatten(0, 1).float(), t, ignore_index=IGNORE)


def param_groups(model: nn.Module, weight_decay: float) -> list[dict]:
    """AdamW: без затухания весов у смещений, норм и эмбеддингов."""
    skip = {id(p) for m in model.modules() if isinstance(m, (nn.Embedding, nn.LayerNorm)) for p in m.parameters()}
    decay, no_decay = [], []
    for p in model.parameters():
        if p.requires_grad:
            (no_decay if p.ndim < 2 or id(p) in skip else decay).append(p)
    return [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}]


def cosine_lr(step: int, warmup: int, total: int, base: float, floor: float = 0.1) -> float:
    if step < warmup:
        return base * (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return base * (floor + (1 - floor) * 0.5 * (1 + math.cos(math.pi * progress)))
