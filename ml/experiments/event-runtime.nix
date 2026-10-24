# CPU-only research environment for all event baselines, including the small GRU.
let
  pkgs = import (builtins.getFlake "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044").outPath {
    config.cudaSupport = false;
  };
in
pkgs.python3.withPackages (p: [ p.lightgbm p.numpy p.pandas p.pyarrow p.pytest p.statsmodels p.torch ])
