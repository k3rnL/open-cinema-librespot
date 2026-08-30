#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPTION = re.compile(r"^\s*(?:-[A-Za-z],\s*)?--([a-z0-9-]+)(?:[= ]([A-Z][A-Z0-9_-]*))?")


def parse_help(text: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for line in text.splitlines():
        match = OPTION.match(line)
        if match:
            options[match.group(1)] = "option" if match.group(2) else "flag"
    return options


def normalized_help(text: str) -> str:
    lines = []
    for index, line in enumerate(text.splitlines()):
        line = line.rstrip()
        if index == 0 and line.startswith("librespot "):
            line = "librespot <verified-build>"
        if line.startswith("Usage: ") and line.endswith(" [<Options>]"):
            line = "Usage: librespot [<Options>]"
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--help-output", type=Path, required=True)
    arguments = parser.parse_args()
    contract = json.loads(
        (ROOT / "option-contract" / "librespot-v0.8.0.json").read_text(encoding="utf-8")
    )
    classified = {
        item["name"]: item for item in contract["options"] if item["kind"] != "conditional-flag"
    }
    help_text = arguments.help_output.read_text(encoding="utf-8")
    observed = parse_help(help_text)
    missing = sorted(set(observed) - set(classified))
    removed = sorted(set(classified) - set(observed))
    type_changes = sorted(
        name
        for name in set(observed) & set(classified)
        if observed[name] != ("flag" if classified[name]["kind"] == "flag" else "option")
        and classified[name]["classification"] not in {"action"}
    )
    help_digest = hashlib.sha256(normalized_help(help_text).encode("utf-8")).hexdigest()
    expected_help_digest = contract.get("normalizedHelpSha256")
    if missing or removed or type_changes or help_digest != expected_help_digest:
        raise SystemExit(
            "librespot option contract drift: "
            f"unclassified={missing}, absent={removed}, typeChanges={type_changes}, "
            f"helpDigest={help_digest}, expectedHelpDigest={expected_help_digest}"
        )
    print(f"verified {len(observed)} librespot v0.8.0 options")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
