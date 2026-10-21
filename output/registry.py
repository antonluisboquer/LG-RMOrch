"""Workflow Registry — Loaded from workflow_config.json.

Single source of truth for step/substep configuration.
Adapted from DocsOrch Agent Factory pattern.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")


@dataclass
class SubstepConfig:
    name: str
    tools: list[str] = field(default_factory=list)


@dataclass
class StepConfig:
    name: str
    phase: str
    plan_file: str = ""
    tools: list[str] = field(default_factory=list)
    substeps: dict[str, SubstepConfig] = field(default_factory=dict)


GENERAL_TOOLS = {"write_todo", "get_workflow_status", "save_step_report"}
SKIP_STEP_TOOLS = {"write_todo", "get_workflow_status"}


def _load_workflow_config() -> dict:
    path = os.path.join(CONFIG_DIR, "workflow_config.json")
    with open(path, "r") as f:
        return json.load(f)


_config = _load_workflow_config()

STEP_ORDER = _config.get("step_order", [])


class _DevMode:
    def __init__(self):
        dev = _config.get("dev_mode", {})
        self.skip_steps = set(dev.get("skip_steps", []))
        self.skip_substeps = set(dev.get("skip_substeps", []))
        self.dry_run = dev.get("dry_run", False)
        self.fixture = dev.get("fixture", {})
        self.source = "config"

    @property
    def enabled(self) -> bool:
        return bool(self.skip_steps or self.skip_substeps)

DEV_MODE = _DevMode()


def get_fixture_config() -> dict:
    return DEV_MODE.fixture


def apply_dev_mode_config(input_config: dict | None = None) -> None:
    if input_config:
        DEV_MODE.skip_steps = set(input_config.get("skip_steps", DEV_MODE.skip_steps))
        DEV_MODE.skip_substeps = set(input_config.get("skip_substeps", DEV_MODE.skip_substeps))
        DEV_MODE.dry_run = input_config.get("dry_run", DEV_MODE.dry_run)
        DEV_MODE.source = "input"


_STEPS: dict[str, StepConfig] = {}

for step_id, step_data in _config.get("steps", {}).items():
    substeps = {}
    for ss_key, ss_data in step_data.get("substeps", {}).items():
        substeps[ss_key] = SubstepConfig(
            name=ss_data.get("name", ""),
            tools=ss_data.get("tools", []),
        )

    _STEPS[step_id] = StepConfig(
        name=step_data.get("name", ""),
        phase=step_data.get("phase", ""),
        plan_file=step_data.get("plan_file", ""),
        tools=step_data.get("tools", []),
        substeps=substeps,
    )


def get_step_config(step_id: str) -> Optional[StepConfig]:
    return _STEPS.get(step_id)


def get_step_number(step_id: str) -> int:
    try:
        return int(step_id.replace("STEP_", ""))
    except ValueError:
        return -1


def get_next_step(step_id: str) -> Optional[str]:
    try:
        idx = STEP_ORDER.index(step_id)
        if idx + 1 < len(STEP_ORDER):
            return STEP_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def is_step_skipped(step_id: str) -> bool:
    if not DEV_MODE.enabled:
        return False
    return step_id in DEV_MODE.skip_steps


def is_substep_skipped(step_id: str, substep_id: str) -> bool:
    if not DEV_MODE.enabled:
        return False
    return substep_id in DEV_MODE.skip_substeps


def get_step_tools(step_id: str) -> list[str]:
    cfg = get_step_config(step_id)
    if not cfg:
        return []
    if is_step_skipped(step_id):
        return list(SKIP_STEP_TOOLS)
    return list(GENERAL_TOOLS | set(cfg.tools))


def get_step_tools_excluding_skipped(
    step_id: str,
    extra_skip_substeps: set[str] | None = None,
) -> set[str]:
    cfg = get_step_config(step_id)
    if not cfg:
        return set()
    if is_step_skipped(step_id):
        return set(SKIP_STEP_TOOLS)

    step_num = get_step_number(step_id)
    allowed = set(GENERAL_TOOLS)

    for ss_key, ss_cfg in cfg.substeps.items():
        full_id = f"{step_num}.{ss_key}"

        if is_substep_skipped(step_id, full_id):
            continue
        if extra_skip_substeps and full_id in extra_skip_substeps:
            continue

        for tool_name in ss_cfg.tools:
            if tool_name:
                allowed.add(tool_name)

    return allowed


def get_tools_for_step(all_tools: list, step_id: str) -> list:
    allowed = set(get_step_tools(step_id))
    return [t for t in all_tools
            if getattr(t, "name", getattr(t, "__name__", "")) in allowed]


def generate_workflow_overview() -> str:
    lines = []
    current_phase = None

    for step_id in STEP_ORDER:
        cfg = get_step_config(step_id)
        if not cfg:
            continue

        if cfg.phase != current_phase:
            current_phase = cfg.phase
            lines.append(f"\n### Phase: {current_phase}")

        step_num = get_step_number(step_id)
        ss_count = len(cfg.substeps)
        skipped = " [SKIPPED]" if is_step_skipped(step_id) else ""
        lines.append(f"- **Step {step_num}** — {cfg.name} ({ss_count} substeps){skipped}")

    return "\n".join(lines)
