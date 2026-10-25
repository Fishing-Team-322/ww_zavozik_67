"""Auxiliary channel evidence does not define native economic categories."""
from zavozik_ml.classify_v2.text import Operation
from zavozik_ml.classify_v2.weak_labels import annotate


def auxiliary(op):
    labels=annotate(Operation(op['direction'],op.get('purpose',''),op.get('counterparty_name','')))
    return dict(channel=labels.channel,tags=list(labels.tags),auxiliary_source=labels.source)
