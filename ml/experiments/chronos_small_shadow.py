"""Pinned larger Chronos comparison on the same development origins.

Uses fewer Monte Carlo paths (200) to keep local memory bounded. Identical
net-flow target and calendar policy as the Tiny experiment; research only.
"""
import sys
from pathlib import Path
import chronos_shadow as experiment
experiment.MODEL='amazon/chronos-t5-small'
experiment.REVISION='a971ba21945c4f1796b17a91fe69214b5f4ad472'
experiment.ChronosNet.name='chronos_small'
if __name__=='__main__':
    # Explicit options after defaults may override paths/scenarios for smoke runs.
    sys.argv=[sys.argv[0],'--paths','200','--scenarios','standard','--out',
        str(Path(__file__).resolve().parents[1]/'data/chronos_small_development.parquet'),*sys.argv[1:]]
    experiment.main()
