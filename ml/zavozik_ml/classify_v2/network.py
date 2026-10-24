"""Training-only torch network. Deployment heads are plain numpy arrays."""
from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F


class MultiTaskEncoder(nn.Module):
    def __init__(self, encoder, n_categories: int, n_channels: int, n_tags: int, pooling: str = "cls"):
        super().__init__()
        self.encoder = encoder
        self.pooling = pooling
        dim = encoder.config.hidden_size
        self.prototypes = nn.Parameter(torch.empty(n_categories, dim))
        nn.init.normal_(self.prototypes, std=.02)
        self.log_scale = nn.Parameter(torch.tensor(math.log(25.0)))
        self.channel = nn.Linear(dim, n_channels)
        self.tags = nn.Linear(dim, n_tags)

    def embeddings(self, **tokens):
        h = self.encoder(**tokens).last_hidden_state
        if self.pooling == "mean":
            m = tokens["attention_mask"].unsqueeze(-1)
            h = (h * m).sum(1) / m.sum(1).clamp(min=1)
        else:
            h = h[:, 0]
        return F.normalize(h, dim=-1)

    def forward(self, **tokens):
        x = self.embeddings(**tokens)
        similarity = x @ F.normalize(self.prototypes, dim=-1).T
        return {"embedding": x, "category_logits": similarity * self.log_scale.clamp(0, math.log(100)).exp(),
                "channel_logits": self.channel(x), "tag_logits": self.tags(x),
                "novelty": (1 - similarity.max(dim=1).values).clamp(0, 1)}


def supervised_contrastive(embedding, labels, temperature=.1, exclude_label: int | None = None):
    similarity = embedding @ embedding.T / temperature
    eye = torch.eye(len(labels), dtype=torch.bool, device=labels.device)
    positive = labels[:, None].eq(labels[None, :]) & ~eye
    if exclude_label is not None:
        positive &= labels[:, None].ne(exclude_label)
    logits = similarity.masked_fill(eye, -1e4)
    log_p = logits - torch.logsumexp(logits, dim=1, keepdim=True)
    count = positive.sum(1)
    valid = count > 0
    if not valid.any():
        return embedding.sum() * 0
    return -((log_p * positive).sum(1) / count.clamp(min=1))[valid].mean()
