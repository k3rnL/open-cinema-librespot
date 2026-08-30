#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import sys

print("fake-pw-cat started", file=sys.stderr, flush=True)
if os.environ.get("FAKE_IGNORE_TERM"):
    signal.signal(signal.SIGTERM, lambda *_arguments: None)
if os.environ.get("FAKE_BRIDGE_EXIT"):
    raise SystemExit(int(os.environ["FAKE_BRIDGE_EXIT"]))
while sys.stdin.buffer.read(4096):
    pass
