"""Pinned larger Chronos comparison on the same development origins.

Uses fewer Monte Carlo paths (200) to keep local memory bounded. Identical
net-flow target and calendar policy as the Tiny experiment; research only.
"""
import sys
import hashlib
import json
from pathlib import Path
import chronos_shadow as experiment
experiment.MODEL='amazon/chronos-t5-small'
experiment.REVISION='a971ba21945c4f1796b17a91fe69214b5f4ad472'
experiment.ChronosNet.name='chronos_small'
if __name__=='__main__':
    # Explicit options after defaults may override paths/scenarios for smoke runs.
    sys.argv=[sys.argv[0],'--paths','200','--scenarios','standard','--out',
        str(Path(__file__).resolve().parents[1]/'data/chronos_small_development.parquet'),*sys.argv[1:]]
    source_at_start=experiment.source_fingerprint()
    experiment.main()
    path=Path(sys.argv[max(i for i,x in enumerate(sys.argv) if x=='--out')+1]).with_suffix('.metadata.json')
    meta=json.loads(path.read_text())
    meta.update(source_sha256_at_start=source_at_start,
        source_changed_during_run=source_at_start!=experiment.source_fingerprint(),
        wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    path.write_text(json.dumps(meta,indent=2))
