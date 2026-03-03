#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - script fails fast without PyYAML
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = ROOT / "agents" / "agents.yaml"
BASE_PATH = ROOT / "k8s" / "base" / "openclaw-config.base.json"
OUT_PATH = ROOT / "k8s" / "base" / "openclaw-config.json"


def _humanize(name: str) -> str:
    if not name:
        return ""
    spaced = re.sub(r"(?<!^)([A-Z])", r" \1", name)
    return spaced.replace("_", " ").strip()


def _load_agents() -> dict:
    if yaml is None:
        raise SystemExit("PyYAML is required to render OpenClaw config.")
    if not AGENTS_PATH.exists():
        raise SystemExit(f"Missing agents config: {AGENTS_PATH}")
    data = yaml.safe_load(AGENTS_PATH.read_text()) or {}
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        return {}
    return agents


def _build_agent_list(agents: dict) -> list[dict]:
    rendered: list[dict] = []
    for role, entry in agents.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("framework") != "openclaw":
            continue
        agent_id = entry.get("openclaw_agent_id")
        if not agent_id:
            raise SystemExit(
                f"OpenClaw agent '{role}' missing openclaw_agent_id in {AGENTS_PATH}"
            )
        display = entry.get("slack_handle") or role
        name = _humanize(str(display)) or agent_id
        rendered.append(
            {
                "id": agent_id,
                "name": name,
                "agentDir": f"/home/node/.openclaw/agents/{agent_id}/agent",
            }
        )
    return rendered


def main() -> int:
    if not BASE_PATH.exists():
        raise SystemExit(f"Missing OpenClaw base config: {BASE_PATH}")
    base = json.loads(BASE_PATH.read_text())
    agents = _load_agents()
    base.setdefault("agents", {}).setdefault("defaults", {})
    base["agents"]["list"] = _build_agent_list(agents)
    OUT_PATH.write_text(json.dumps(base, indent=2) + "\n")
    print(f"Rendered {OUT_PATH} from {AGENTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
