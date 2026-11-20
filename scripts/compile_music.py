#!/usr/bin/env python3
"""Compile a Music DSL file and its arrangement manifest JSON into MADS assembly."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ArrangementConfig:
    """Parsed arrangement parameters from an atari-music arrangement manifest."""

    channel_assignments: dict[int, str]
    program_change_policy: str
    player_version: str

    @classmethod
    def from_manifest(cls, data: Mapping[str, Any]) -> ArrangementConfig:
        """Extract arrangement CLI parameters from manifest dictionary."""
        arr = data.get("arrangement")
        if not isinstance(arr, Mapping):
            raise ValueError("Invalid arrangement manifest: missing 'arrangement' object.")

        raw_ch = arr.get("channel_assignments") or {}
        if not isinstance(raw_ch, Mapping):
            raise ValueError("Invalid arrangement manifest: 'channel_assignments' must be a mapping.")

        assignments: dict[int, str] = {}
        for ch_key, inst_id in sorted(raw_ch.items(), key=lambda item: int(item[0])):
            if inst_id is not None and str(inst_id).strip():
                ch_num = int(ch_key)
                if not 1 <= ch_num <= 4:
                    raise ValueError(f"Channel number {ch_num} out of range 1..4.")
                assignments[ch_num] = str(inst_id).strip()

        policy = str(arr.get("program_change_policy") or "preserve").strip().lower()
        if policy not in {"preserve", "replace", "remove"}:
            raise ValueError(f"Unsupported program_change_policy '{policy}'.")

        eff_ver = arr.get("effective_format_version")
        backend = str(arr.get("resolved_target_backend") or arr.get("target_backend") or "").lower()
        req_ver = str(arr.get("requested_player_version") or "auto").strip().lower()
        if eff_ver == 2 or backend == "xex_v2":
            player_version = "v2"
        elif eff_ver == 1 or backend == "xex_v1":
            player_version = "v1"
        elif req_ver in {"auto", "v1", "v2"}:
            player_version = req_ver
        else:
            player_version = "auto"

        return cls(
            channel_assignments=assignments,
            program_change_policy=policy,
            player_version=player_version,
        )


def load_arrangement_config(manifest_path: Path) -> ArrangementConfig:
    """Load and validate an arrangement manifest JSON file."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"Arrangement file '{manifest_path}' must contain a JSON object.")
    return ArrangementConfig.from_manifest(raw)


def build_arrange_command(
    python_exe: str,
    json_path: Path,
    asm_output: Path,
    config: ArrangementConfig,
    catalog_path: Path | None = None,
) -> list[str]:
    """Construct the `atari_music.cli arrange` command list from `ArrangementConfig`."""
    cmd = [
        python_exe,
        "-m",
        "atari_music.cli",
        "arrange",
        str(json_path),
    ]
    for ch, inst_id in sorted(config.channel_assignments.items()):
        cmd.extend(["--channel-instrument", f"{ch}={inst_id}"])
    cmd.extend(["--program-change-policy", config.program_change_policy])
    cmd.extend(["--player-version", config.player_version])
    if catalog_path is not None:
        cmd.extend(["--instrument-catalog", str(catalog_path)])
    cmd.extend(["--output-asm", str(asm_output)])
    return cmd


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for compiling DSL + arrangement manifest to MADS ASM."""
    parser = argparse.ArgumentParser(
        description="Compile Music DSL and arrangement manifest JSON into MADS ASM."
    )
    parser.add_argument("--dsl", type=Path, required=True, help="Input .dsl file path.")
    parser.add_argument(
        "--arrangement",
        type=Path,
        required=True,
        help="Input .arrangement.json manifest path.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        required=True,
        help="Intermediate composition JSON output path.",
    )
    parser.add_argument(
        "--asm-output",
        type=Path,
        required=True,
        help="Output MADS assembly (.asm) path.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional SSOT instrument catalog JSON path.",
    )
    args = parser.parse_args(argv)

    if not args.dsl.exists():
        sys.stderr.write(f"ERROR: DSL file not found: {args.dsl}\n")
        return 1
    if not args.arrangement.exists():
        sys.stderr.write(f"ERROR: Arrangement file not found: {args.arrangement}\n")
        return 1

    try:
        config = load_arrangement_config(args.arrangement)
    except (ValueError, json.JSONDecodeError) as err:
        sys.stderr.write(f"ERROR: {err}\n")
        return 1

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.asm_output.parent.mkdir(parents=True, exist_ok=True)

    import_cmd = [
        sys.executable,
        "-m",
        "atari_music.cli",
        "import-dsl",
        str(args.dsl),
        "--output-json",
        str(args.json_output),
    ]
    res_import = subprocess.run(import_cmd, check=False)
    if res_import.returncode != 0:
        return res_import.returncode

    arrange_cmd = build_arrange_command(
        python_exe=sys.executable,
        json_path=args.json_output,
        asm_output=args.asm_output,
        config=config,
        catalog_path=args.catalog,
    )
    res_arrange = subprocess.run(arrange_cmd, check=False)
    return res_arrange.returncode


if __name__ == "__main__":
    sys.exit(main())
