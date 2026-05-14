"""Render sing-box config from template + PROXY_NODES_JSON env.

Reads ``singbox/config.template.json`` and ``$PROXY_NODES_JSON`` (a JSON array of
SOCKS5 node specs), then writes the materialised config to ``singbox/config.json``.

Each node spec must contain ``server``, ``port``, ``username``, ``password``;
``tag`` is optional (auto-generated if missing). Failure modes (missing env,
malformed JSON, empty list, missing required fields) exit non-zero with a
message so the workflow fails fast before launching sing-box.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "singbox" / "config.template.json"
OUTPUT_PATH = ROOT / "singbox" / "config.json"
PLACEHOLDER = "__PLACEHOLDER__"


def die(msg: str) -> None:
    print(f"[render_singbox] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_nodes() -> list[dict]:
    raw = os.getenv("PROXY_NODES_JSON", "").strip()
    if not raw:
        die("PROXY_NODES_JSON is not set")
    try:
        nodes = json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"PROXY_NODES_JSON is not valid JSON: {e}")
    if not isinstance(nodes, list) or not nodes:
        die("PROXY_NODES_JSON must be a non-empty JSON array")
    return nodes


def build_socks_outbound(idx: int, node: dict) -> dict:
    required = ("server", "port", "username", "password")
    missing = [k for k in required if node.get(k) in (None, "")]
    if missing:
        die(f"node #{idx} missing required fields: {missing}")
    tag = str(node.get("tag") or f"node-{idx:02d}").strip()
    try:
        port = int(node["port"])
    except (TypeError, ValueError):
        die(f"node #{idx} ({tag}): port must be integer-like")
    return {
        "type": "socks",
        "tag": tag,
        "server": str(node["server"]).strip(),
        "server_port": port,
        "version": "5",
        "username": str(node["username"]),
        "password": str(node["password"]),
        "network": "tcp",
    }


def main() -> None:
    if not TEMPLATE_PATH.exists():
        die(f"template not found: {TEMPLATE_PATH}")
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

    nodes = load_nodes()
    socks_outbounds = [build_socks_outbound(i, n) for i, n in enumerate(nodes, start=1)]
    tags = [o["tag"] for o in socks_outbounds]
    if len(set(tags)) != len(tags):
        die(f"duplicate node tags detected: {tags}")

    new_outbounds: list[dict] = []
    for ob in template.get("outbounds", []):
        if ob.get("type") == "urltest" and ob.get("outbounds") == [PLACEHOLDER]:
            ob = {**ob, "outbounds": tags}
        if ob.get("type") == "selector" and ob.get("tag") == "proxy":
            ob = {**ob, "outbounds": ["urltest", *tags]}
        new_outbounds.append(ob)
    new_outbounds = [*socks_outbounds, *new_outbounds]
    template["outbounds"] = new_outbounds

    OUTPUT_PATH.write_text(
        json.dumps(template, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[render_singbox] wrote {OUTPUT_PATH} with {len(socks_outbounds)} node(s): {tags}")


if __name__ == "__main__":
    main()
