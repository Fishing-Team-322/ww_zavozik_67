"""Private binary-stdio CPU encoder worker, isolated from LightGBM/OpenMP.

Only the parent process supplies text. No sockets, external APIs, persistent
operation cache, or customer-data logging. stdout is exclusively the protocol.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import sys

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import torch  # initialize its native libraries before numpy/other frameworks

from .model import TorchEncoder


def read_exact(stream, size):
    value = bytearray()
    while len(value) < size:
        part = stream.read(size - len(value))
        if not part:
            raise EOFError
        value.extend(part)
    return bytes(value)


def send(stream, status, payload):
    stream.write(status + struct.pack("!I", len(payload)) + payload)
    stream.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.directory / "config.json").read_text())
    encoder = TorchEncoder(args.directory, config)
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    send(out, b"R", struct.pack("!I", config["embedding_dim"]))
    while True:
        try:
            size = struct.unpack("!I", read_exact(inp, 4))[0]
        except EOFError:
            return
        if size > 16 << 20:
            send(out, b"E", b"request exceeds worker limit")
            return
        try:
            texts = json.loads(read_exact(inp, size))
            if not isinstance(texts, list) or len(texts) > 1024 or any(not isinstance(t, str) for t in texts):
                raise ValueError("invalid text batch")
            values = encoder(texts)
            payload = struct.pack("!II", len(values), config["embedding_dim"]) + values.astype("<f4").tobytes()
            send(out, b"O", payload)
        except Exception as error:
            # No error message or repr containing operation text leaves worker.
            send(out, b"E", type(error).__name__.encode("ascii", errors="replace"))


if __name__ == "__main__":
    main()
