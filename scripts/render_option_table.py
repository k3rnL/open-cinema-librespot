#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def escaped(value: object) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def representation(item: dict[str, object]) -> str:
    if item.get("representation"):
        return escaped(item["representation"])
    if item.get("field"):
        suffix = " (inverted)" if item.get("invert") is True else ""
        return f"Typed field `{escaped(item['field'])}`{suffix}"
    if item.get("reason"):
        return escaped(item["reason"])
    if item.get("value") is not None:
        return f"Fixed to `{escaped(item['value'])}`"
    return "Classified by the launch serializer"


def main() -> int:
    contract = json.loads(
        (ROOT / "option-contract" / "librespot-v0.8.0.json").read_text(encoding="utf-8")
    )
    print("# Librespot 0.8.0 option compatibility\n")
    print(
        "This table is generated from the complete pinned option contract. "
        "CI compares both option types and the normalized full help text so changed choices or "
        "semantics require an explicit review.\n"
    )
    print("| Option | Kind | Open Cinema state | Representation |")
    print("| --- | --- | --- | --- |")
    for item in contract["options"]:
        print(
            f"| `--{escaped(item['name'])}` | {escaped(item['kind'])} | "
            f"{escaped(item['classification'])} | {representation(item)} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
