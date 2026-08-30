#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import sys
import time

token = os.environ.get("LIBRESPOT_ACCESS_TOKEN", "")
print(f"fake-librespot started token={token}", file=sys.stderr, flush=True)
if os.environ.get("FAKE_IGNORE_TERM"):
    signal.signal(signal.SIGTERM, lambda *_arguments: None)
if os.environ.get("FAKE_LIBRESPOT_EXIT"):
    raise SystemExit(int(os.environ["FAKE_LIBRESPOT_EXIT"]))

block = b"\x00" * 4096
try:
    while True:
        sys.stdout.buffer.write(block)
        sys.stdout.buffer.flush()
        time.sleep(0.005)
except (BrokenPipeError, KeyboardInterrupt):
    pass
