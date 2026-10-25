# Standalone CPU experiment environment; does not change the serving image.
let
  pkgs = import (builtins.getFlake "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044").outPath {};
in
pkgs.python3.withPackages (p: [ p.lightgbm p.numpy p.pandas p.pyarrow p.pytest p.statsmodels ])
