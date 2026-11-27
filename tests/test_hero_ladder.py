"""Comprehensive pytest + py65 tests for Hero ladder climbing, tag validation & parity."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from room_editor.io.yaml_io import load_project
from room_editor.model.project import ROOM_HEIGHT, ROOM_WIDTH
from scripts.rooms_compile import RoomCompileError, compile_project

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"
ROOMS_YAML = ROOT_DIR / "rooms.yaml"

HPOSP0 = 0xD000

# Active-low Joystick 0 direction masks (bits 0..3: UP, DOWN, LEFT, RIGHT; 0 = pressed)
JOY_CENTRE = 0x0F
JOY_UP = 0x0E
JOY_DOWN = 0x0D
JOY_LEFT = 0x0B
JOY_RIGHT = 0x07
JOY_UP_LEFT = 0x0A
JOY_UP_RIGHT = 0x06
JOY_DOWN_LEFT = 0x09
JOY_DOWN_RIGHT = 0x05


def _parse_labels(lab_path: Path) -> dict[str, int]:
    assert lab_path.exists(), f"Missing {lab_path}; run 'make all' first."
    labels: dict[str, int] = {}
    pat = re.compile(r"^[0-9a-fA-F]{2}\t([0-9a-fA-F]{4})\t([A-Za-z0-9_.\@?]+)")
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if m:
            labels[m.group(2).upper()] = int(m.group(1), 16)
    return labels


def _load_xex(xex_path: Path, mem: bytearray) -> None:
    assert xex_path.exists(), f"Missing {xex_path}; run 'make all' first."
    data = xex_path.read_bytes()
    idx = 0
    n = len(data)
    while idx < n:
        if idx + 2 <= n and data[idx] == 0xFF and data[idx + 1] == 0xFF:
            idx += 2
            if idx == n:
                break
        start = data[idx] | (data[idx + 1] << 8)
        end = data[idx + 2] | (data[idx + 3] << 8)
        idx += 4
        length = end - start + 1
        mem[start : end + 1] = data[idx : idx + length]
        idx += length


def _run_subroutine(mpu: MPU, addr: int, max_steps: int = 300_000) -> int:
    mpu.sp = 0xFD
    mpu.stPushWord(0x0100 - 1)
    mpu.memory[0x0100] = 0x00
    mpu.pc = addr
    c0 = mpu.processorCycles
    steps = 0
    while mpu.pc != 0x0100 and steps < max_steps:
        mpu.step()
        steps += 1
    assert mpu.pc == 0x0100, f"Subroutine ${addr:04X} did not return within {max_steps} steps"
    return int(mpu.processorCycles - c0)


def _fresh_emu() -> tuple[MPU, bytearray, dict[str, int]]:
    mem = bytearray(65536)
    _load_xex(XEX_PATH, mem)
    labels = _parse_labels(LAB_PATH)
    mpu = MPU(memory=mem)
    mpu.reset()
    return mpu, mem, labels


def _build_grid(
    *,
    rects: list[tuple[int, int, int, int]] | None = None,
    cells: list[tuple[int, int]] | None = None,
) -> list[list[bool]]:
    """Build a synthetic 40x24 bool bitmap from rects=(col_a, col_b, row_a, row_b) and cells=(col, row)."""
    grid = [[False] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
    for col_a, col_b, row_a, row_b in rects or []:
        for r in range(row_a, row_b + 1):
            for c in range(col_a, col_b + 1):
                grid[r][c] = True
    for col, row in cells or []:
        grid[row][col] = True
    return grid


def _poke_bitmap(mem: bytearray | ObservableMemory, addr: int, grid: list[list[bool]]) -> None:
    for i in range(ROOM_HEIGHT * 5):
        mem[addr + i] = 0
    for r in range(ROOM_HEIGHT):
        row_base = addr + r * 5
        for c in range(ROOM_WIDTH):
            if grid[r][c]:
                mem[row_base + (c >> 3)] |= 0x80 >> (c & 7)


def _read_bitmap(mem: bytearray | ObservableMemory, addr: int) -> list[list[bool]]:
    out: list[list[bool]] = []
    for r in range(ROOM_HEIGHT):
        row_base = addr + r * 5
        out.append([bool(mem[row_base + (c >> 3)] & (0x80 >> (c & 7))) for c in range(ROOM_WIDTH)])
    return out


def _frame_bytes(mem: bytearray | ObservableMemory, labels: dict[str, int], set_id: int, frame_idx: int) -> list[int]:
    base = mem[labels["HERO_SET_BASE"] + set_id]
    ptr = mem[labels["HERO_FRAME_LO"] + base + frame_idx] | (
        mem[labels["HERO_FRAME_HI"] + base + frame_idx] << 8
    )
    h = labels["HERO_SPRITE_HEIGHT"]
    return list(mem[ptr : ptr + h])


def _assert_pmg_clean(
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    *,
    x_cc: int,
    y_pmg: int,
    anim_set: int,
    anim_frame: int,
) -> None:
    pmg_p0 = labels["PMG_P0"]
    h = labels["HERO_SPRITE_HEIGHT"]
    expected = [0] * 256
    expected[y_pmg : y_pmg + h] = _frame_bytes(mem, labels, anim_set, anim_frame)
    assert list(mem[pmg_p0 : pmg_p0 + 256]) == expected
    assert mem[HPOSP0] == labels["PLAYFIELD_LEFT_CC"] + x_cc


def _init_hero(
    mpu: MPU,
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    block_grid: list[list[bool]],
    ladder_grid: list[list[bool]],
    start_x_cell: int,
    start_y_cell: int,
) -> None:
    _poke_bitmap(mem, labels["ROOM_BLOCK_MAP"], block_grid)
    _poke_bitmap(mem, labels["ROOM_LADDER_MAP"], ladder_grid)
    mem[labels["ZP_JOY_CURR"]] = JOY_CENTRE
    mem[labels["ZP_FIRE_PRESSED"]] = 0
    mpu.x = start_x_cell
    mpu.y = start_y_cell
    _run_subroutine(mpu, labels["HERO_INIT"])


@dataclass
class HeroLadderModel:
    """Reference Python model mirroring 6502 hero physics including ON_LADDER."""

    block_grid: list[list[bool]]
    ladder_grid: list[list[bool]]
    labels: dict[str, int]
    set_counts: dict[int, int]
    set_durs: dict[int, int]
    fall_steps: list[int]
    jump_steps: list[int]
    x: int = 0
    y: int = 0
    state: int = 0
    facing: int = 0
    anim_set: int = 0
    anim_frame: int = 0
    anim_timer: int = 0
    fall_idx: int = 0
    jump_idx: int = 0
    jump_dir: int = 0xFF
    walk_sub: int = 0
    fell_out: int = 0
    dirty: int = 0
    fire_pressed: int = 0

    @classmethod
    def from_emu(
        cls,
        mem: bytearray | ObservableMemory,
        labels: dict[str, int],
        block_grid: list[list[bool]],
        ladder_grid: list[list[bool]],
        start_x_cell: int,
        start_y_cell: int,
    ) -> "HeroLadderModel":
        num_sets = labels["HERO_NUM_SETS"]
        set_counts = {s: mem[labels["HERO_SET_COUNT"] + s] for s in range(1, num_sets + 1)}
        set_durs = {s: mem[labels["HERO_SET_DUR"] + s] for s in range(1, num_sets + 1)}
        fall_steps = list(
            mem[labels["HERO_FALL_STEPS"] : labels["HERO_FALL_STEPS"] + labels["HERO_FALL_STEP_COUNT"]]
        )
        jump_steps = list(
            mem[labels["HERO_JUMP_STEPS"] : labels["HERO_JUMP_STEPS"] + labels["HERO_JUMP_STEP_COUNT"]]
        )
        m = cls(
            block_grid=block_grid,
            ladder_grid=ladder_grid,
            labels=labels,
            set_counts=set_counts,
            set_durs=set_durs,
            fall_steps=fall_steps,
            jump_steps=jump_steps,
        )
        m.x = start_x_cell * 4
        m.y = (start_y_cell + 1) * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]
        m.facing = labels["HERO_START_FACING"]
        if m.check_support():
            m.enter_standing()
        else:
            m.enter_falling()
        m.dirty = 0
        return m

    def footprint_cols(self, x_cc: int | None = None) -> tuple[int, int]:
        x = self.x if x_cc is None else x_cc
        w = self.labels["HERO_COLLISION_WIDTH_CC"]
        return x >> 2, (x + w - 1) >> 2

    def row_range(self, grid: list[list[bool]], row: int, col_a: int, col_b: int) -> bool:
        if row >= ROOM_HEIGHT or col_a >= ROOM_WIDTH:
            return False
        cb = min(ROOM_WIDTH - 1, col_b)
        if cb < col_a:
            return False
        return any(grid[row][c] for c in range(col_a, cb + 1))

    def row_range_blocked(self, row: int, col_a: int, col_b: int) -> bool:
        return self.row_range(self.block_grid, row, col_a, col_b)

    def row_range_ladder(self, row: int, col_a: int, col_b: int) -> bool:
        return self.row_range(self.ladder_grid, row, col_a, col_b)

    def row_range_support(self, row: int, col_a: int, col_b: int) -> bool:
        return self.row_range_blocked(row, col_a, col_b) or self.row_range_ladder(row, col_a, col_b)

    def col_range_ladder(self, col: int, row_a: int, row_b: int) -> bool:
        if col >= ROOM_WIDTH or row_a >= ROOM_HEIGHT:
            return False
        rb = min(ROOM_HEIGHT - 1, row_b)
        if rb < row_a:
            return False
        return any(self.ladder_grid[r][col] for r in range(row_a, rb + 1))

    def body_rows(self, y_pmg: int) -> tuple[int, int] | None:
        top_to_bot = self.labels["HERO_TOP_TO_PF_BOTTOM"]
        last_pf = y_pmg - (top_to_bot + 1)
        if last_pf < 0:
            return None
        bot_row = min(ROOM_HEIGHT - 1, last_pf >> 3)
        top_pf = y_pmg - self.labels["PLAYFIELD_TOP_PMG_Y"]
        if top_pf < 0:
            top_row = 0
        else:
            top_row = top_pf >> 3
            if top_row >= ROOM_HEIGHT:
                return None
        return top_row, bot_row

    def blocked_at(self, cand_x: int, cand_y: int) -> bool:
        rows = self.body_rows(cand_y)
        if rows is None:
            return False
        top_row, bot_row = rows
        col_l, col_r = self.footprint_cols(cand_x)
        return any(
            self.block_grid[r][c]
            for c in range(col_l, min(ROOM_WIDTH - 1, col_r) + 1)
            for r in range(top_row, bot_row + 1)
        )

    def check_support(self) -> bool:
        bottom_pf = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
        if (bottom_pf & 7) != 0:
            return False
        row = bottom_pf >> 3
        col_l, col_r = self.footprint_cols()
        return self.row_range_support(row, col_l, col_r)

    def ladder_under_feet(self) -> bool:
        bottom_pf = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
        if (bottom_pf & 7) != 0:
            return False
        row = bottom_pf >> 3
        col_l, col_r = self.footprint_cols()
        return self.row_range_ladder(row, col_l, col_r)

    def can_descend_ladder(self) -> bool:
        bottom_pf = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
        if (bottom_pf & 7) != 0:
            return False
        row = bottom_pf >> 3
        col_l, col_r = self.footprint_cols()
        return self.row_range_ladder(row, col_l, col_r) and not self.row_range_blocked(row, col_l, col_r)

    def ladder_behind(self) -> bool:
        rows = self.body_rows(self.y)
        if rows is None:
            return False
        top_row, bot_row = rows
        col_l, col_r = self.footprint_cols()
        return any(self.col_range_ladder(c, top_row, bot_row) for c in range(col_l, col_r + 1))

    def try_step_x(self, direction: int, step_cc: int) -> bool:
        max_x = self.labels["HERO_MAX_X_CC"]
        cand = min(max_x, self.x + step_cc) if direction == 0 else max(0, self.x - step_cc)
        if cand == self.x:
            return False
        if not self.blocked_at(cand, self.y):
            self.x = cand
            self.dirty = 1
            return True
        return False

    def try_ladder_step_x(self, direction: int, step_cc: int) -> bool:
        max_x = self.labels["HERO_MAX_X_CC"]
        cand = min(max_x, self.x + step_cc) if direction == 0 else max(0, self.x - step_cc)
        if cand == self.x:
            return False
        if self.blocked_at(cand, self.y):
            return False
        rows = self.body_rows(self.y)
        if rows is None:
            return False
        top_row, bot_row = rows
        col_l, col_r = self.footprint_cols(cand)
        lead_col = col_r if direction == 0 else col_l
        if not self.col_range_ladder(lead_col, top_row, bot_row):
            return False
        self.x = cand
        self.dirty = 1
        return True

    def stand_set_for(self, facing: int) -> int:
        return self.labels["HERO_WALK_RIGHT"] if facing == 0 else self.labels["HERO_WALK_LEFT"]

    def jump_set_for(self, facing: int) -> int:
        return self.labels["HERO_JUMP_RIGHT"] if facing == 0 else self.labels["HERO_JUMP_LEFT"]

    def squat_set_for(self, facing: int) -> int:
        return self.labels["HERO_SQUAT_RIGHT"] if facing == 0 else self.labels["HERO_SQUAT_LEFT"]

    def tick_anim(self) -> None:
        self.anim_timer -= 1
        if self.anim_timer != 0:
            return
        self.anim_timer = self.set_durs[self.anim_set]
        self.anim_frame = (self.anim_frame + 1) % self.set_counts[self.anim_set]
        self.dirty = 1

    def tick_walk_anim(self) -> None:
        self.anim_timer -= 1
        if self.anim_timer != 0:
            return
        self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
        self.anim_frame = (self.anim_frame + 1) % self.set_counts[self.anim_set]
        self.dirty = 1

    def enter_standing(self) -> None:
        self.state = self.labels["HERO_STATE_STANDING"]
        self.fall_idx = 0
        self.walk_sub = 0
        self.jump_dir = self.labels["HERO_JUMP_DIR_NONE"]
        self.anim_set = self.stand_set_for(self.facing)
        self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
        self.anim_frame = self.labels["HERO_STAND_FRAME"]
        self.dirty = 1

    def enter_falling(self) -> None:
        self.state = self.labels["HERO_STATE_FALLING"]
        self.anim_set = self.labels["HERO_FALL_SET"]
        self.anim_timer = self.set_durs[self.anim_set]
        self.anim_frame = 0
        self.fall_idx = 0
        self.walk_sub = 0
        self.jump_dir = self.labels["HERO_JUMP_DIR_NONE"]
        self.dirty = 1

    def enter_ladder(self) -> None:
        self.state = self.labels["HERO_STATE_ON_LADDER"]
        self.anim_set = self.labels["HERO_LADDER_SET"]
        self.anim_timer = self.set_durs[self.anim_set]
        self.anim_frame = 0
        self.fall_idx = 0
        self.walk_sub = 0
        self.jump_dir = self.labels["HERO_JUMP_DIR_NONE"]
        self.dirty = 1

    def jump_from_ladder(self, joy_byte: int) -> None:
        self.fire_pressed = 0
        lr = joy_byte & 0x0C
        if lr == 0x08:  # LEFT only
            d = 1
        elif lr == 0x04:  # RIGHT only
            d = 0
        else:
            d = self.facing
        self.facing = d
        self.jump_dir = d
        self.anim_set = self.jump_set_for(d)
        self.anim_timer = self.set_durs[self.anim_set]
        self.anim_frame = 0
        self.jump_idx = 0
        self.walk_sub = 0
        self.state = self.labels["HERO_STATE_JUMPING"]
        self.dirty = 1
        self._step_jump(joy_byte)

    @staticmethod
    def read_input(joy_byte: int) -> int:
        tbl = {
            0x05: 5,
            0x06: 3,
            0x07: 1,
            0x09: 6,
            0x0A: 4,
            0x0B: 2,
            0x0D: 7,
            0x0E: 8,
        }
        return tbl.get(joy_byte & 0x0F, 0)

    def step(self, joy_byte: int, fire_pressed: int = 0) -> None:
        self.dirty = 0
        self.fire_pressed = fire_pressed
        st = self.state
        if st == self.labels["HERO_STATE_STANDING"]:
            if not self.check_support():
                self.enter_falling()
                return
            if self.fire_pressed and self.ladder_under_feet():
                self.jump_from_ladder(joy_byte)
                return
            cmd = self.read_input(joy_byte)
            if cmd == 0:
                self._step_idle()
            elif cmd in (1, 2):
                self._step_walk(cmd)
            elif cmd in (3, 4):
                d = cmd - 3
                self.facing = d
                self.jump_dir = d
                self.anim_set = self.jump_set_for(d)
                self.anim_timer = self.set_durs[self.anim_set]
                self.anim_frame = 0
                self.jump_idx = 0
                self.walk_sub = 0
                self.state = self.labels["HERO_STATE_JUMPING"]
                self.dirty = 1
                self._step_jump(joy_byte)
            elif cmd == 8:
                if self.ladder_behind():
                    self.enter_ladder()
                    self._step_ladder(joy_byte)
                else:
                    self._step_idle()
            else:
                if self.can_descend_ladder():
                    self.enter_ladder()
                    self._step_ladder(joy_byte)
                else:
                    if cmd != 7:
                        self.facing = cmd - 5
                    self.anim_set = self.squat_set_for(self.facing)
                    self.anim_timer = self.set_durs[self.anim_set]
                    self.anim_frame = 0
                    self.walk_sub = 0
                    self.state = self.labels["HERO_STATE_SQUATTING"]
                    self.dirty = 1
        elif st == self.labels["HERO_STATE_FALLING"]:
            self._step_fall(joy_byte)
        elif st == self.labels["HERO_STATE_JUMPING"]:
            self._step_jump(joy_byte)
        elif st == self.labels["HERO_STATE_SQUATTING"]:
            self._step_squat(joy_byte)
        else:
            self._step_ladder(joy_byte)

    def _step_idle(self) -> None:
        self.walk_sub = 0
        if self.anim_set != self.stand_set_for(self.facing) or self.anim_frame != self.labels["HERO_STAND_FRAME"]:
            self.enter_standing()

    def _step_walk(self, cmd: int) -> None:
        d = cmd - 1
        self.facing = d
        want_set = self.stand_set_for(d)
        if self.anim_set != want_set:
            self.anim_set = want_set
            self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
            self.anim_frame = self.labels["HERO_STAND_FRAME"]
            self.walk_sub = 0
            self.dirty = 1
        if self.walk_sub != 0:
            self.walk_sub -= 1
            self.tick_walk_anim()
            return
        self.walk_sub = self.labels["HERO_WALK_SPEED_SUBSTEPS"] - 1
        if self.try_step_x(d, self.labels["HERO_WALK_STEP_CC"]):
            self.tick_walk_anim()
            if not self.check_support():
                self.enter_falling()
        else:
            self.walk_sub = 0
            if self.anim_frame != self.labels["HERO_STAND_FRAME"]:
                self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
                self.anim_frame = self.labels["HERO_STAND_FRAME"]
                self.dirty = 1

    def _step_jump(self, joy_byte: int) -> None:
        if self.jump_idx != 0 and self.read_input(joy_byte) == 8 and self.ladder_behind():
            self.enter_ladder()
            return
        min_y = self.labels["HERO_MIN_PMG_Y"]
        if self.jump_idx >= len(self.jump_steps) or self.y <= min_y:
            self.state = self.labels["HERO_STATE_FALLING"]
            self.fall_idx = 0
        else:
            step = self.jump_steps[self.jump_idx]
            self.jump_idx += 1
            cand = self.y - step
            hit_top = cand < min_y
            if hit_top:
                cand = min_y
            pf_top = self.labels["PLAYFIELD_TOP_PMG_Y"]
            old_hr = (self.y - pf_top) >> 3
            new_hr = (cand - pf_top) >> 3
            if new_hr != old_hr:
                col_l, col_r = self.footprint_cols()
                if self.row_range_blocked(new_hr, col_l, col_r):
                    snapped = ((new_hr + 1) << 3) + pf_top
                    if snapped != self.y:
                        self.y = snapped
                        self.dirty = 1
                    self.state = self.labels["HERO_STATE_FALLING"]
                    self.fall_idx = 0
                else:
                    self.y = cand
                    self.dirty = 1
                    if hit_top or self.jump_idx >= len(self.jump_steps):
                        self.state = self.labels["HERO_STATE_FALLING"]
                        self.fall_idx = 0
            else:
                self.y = cand
                self.dirty = 1
                if hit_top or self.jump_idx >= len(self.jump_steps):
                    self.state = self.labels["HERO_STATE_FALLING"]
                    self.fall_idx = 0
        if self.jump_dir != self.labels["HERO_JUMP_DIR_NONE"]:
            self.try_step_x(self.jump_dir, self.labels["HERO_JUMP_SPEED_CC"])
        self.tick_anim()

    def _step_fall(self, joy_byte: int) -> None:
        if self.read_input(joy_byte) == 8 and self.ladder_behind():
            self.enter_ladder()
            return
        if self.jump_dir != self.labels["HERO_JUMP_DIR_NONE"]:
            self.try_step_x(self.jump_dir, self.labels["HERO_JUMP_SPEED_CC"])
        step = self.fall_steps[self.fall_idx]
        if self.fall_idx < len(self.fall_steps) - 1:
            self.fall_idx += 1
        old_bot = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
        old_row = old_bot >> 3
        new_bot = old_bot + step
        new_row = new_bot >> 3
        if new_row != old_row:
            col_l, col_r = self.footprint_cols()
            if self.row_range_support(new_row, col_l, col_r):
                self.y = (new_row << 3) + self.labels["HERO_TOP_TO_PF_BOTTOM"]
                self.enter_standing()
                return
        new_y = new_bot + self.labels["HERO_TOP_TO_PF_BOTTOM"]
        if new_y >= self.labels["PLAYFIELD_BOTTOM_PMG_Y"]:
            self.y = new_y
            self.jump_dir = self.labels["HERO_JUMP_DIR_NONE"]
            self.fell_out = 1
            return
        self.y = new_y
        self.dirty = 1
        self.tick_anim()

    def _step_squat(self, joy_byte: int) -> None:
        if not self.check_support():
            self.enter_falling()
            return
        cmd = self.read_input(joy_byte)
        if cmd < 5 or cmd > 7:
            self.enter_standing()
            return
        if cmd != 7:
            nf = cmd - 5
            if nf != self.facing:
                self.facing = nf
                self.anim_set = self.squat_set_for(nf)
                self.anim_timer = self.set_durs[self.anim_set]
                self.anim_frame = 0
                self.dirty = 1
                return
        if self.anim_frame + 1 < self.set_counts[self.anim_set]:
            self.anim_timer -= 1
            if self.anim_timer == 0:
                self.anim_timer = self.set_durs[self.anim_set]
                self.anim_frame += 1
                self.dirty = 1

    def _step_ladder(self, joy_byte: int) -> None:
        if self.fire_pressed:
            self.jump_from_ladder(joy_byte)
            return
        moved = False
        lr = joy_byte & 0x0C
        if lr in (0x08, 0x04):
            d = 1 if lr == 0x08 else 0
            self.facing = d
            if self.walk_sub != 0:
                self.walk_sub -= 1
            else:
                self.walk_sub = self.labels["HERO_WALK_SPEED_SUBSTEPS"] - 1
                if self.try_ladder_step_x(d, self.labels["HERO_WALK_STEP_CC"]):
                    moved = True
                else:
                    self.walk_sub = 0
        else:
            self.walk_sub = 0

        ud = joy_byte & 0x03
        climb_spd = self.labels["HERO_CLIMB_SPEED"]
        min_y = self.labels["HERO_MIN_PMG_Y"]
        if ud == 0x02:  # UP only
            cand_y = max(min_y, self.y - climb_spd)
            if cand_y != self.y and not self.blocked_at(self.x, cand_y):
                self.y = cand_y
                self.dirty = 1
                moved = True
                bot_pf = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
                if (bot_pf & 7) == 0 and self.ladder_under_feet() and not self.ladder_behind():
                    self.enter_standing()
                    return
                if not self.ladder_behind():
                    if self.ladder_under_feet():
                        self.enter_standing()
                    else:
                        self.enter_falling()
                    return
        elif ud == 0x01:  # DOWN only
            old_bot = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
            old_row = old_bot >> 3
            new_bot = old_bot + climb_spd
            new_row = new_bot >> 3
            if new_row != old_row:
                col_l, col_r = self.footprint_cols()
                if self.row_range_blocked(new_row, col_l, col_r):
                    self.y = (new_row << 3) + self.labels["HERO_TOP_TO_PF_BOTTOM"]
                    self.enter_standing()
                    return
            cand_y = new_bot + self.labels["HERO_TOP_TO_PF_BOTTOM"]
            if cand_y >= self.labels["PLAYFIELD_BOTTOM_PMG_Y"]:
                self.y = cand_y
                self.jump_dir = self.labels["HERO_JUMP_DIR_NONE"]
                self.fell_out = 1
                return
            self.y = cand_y
            self.dirty = 1
            moved = True
            bot_row = (self.y - (self.labels["HERO_TOP_TO_PF_BOTTOM"] + 1)) >> 3
            col_l, col_r = self.footprint_cols()
            if not self.row_range_ladder(bot_row, col_l, col_r):
                self.enter_falling()
                return

        if moved:
            self.tick_anim()


def _step_and_check(
    mpu: MPU,
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    model: HeroLadderModel,
    joy_byte: int,
    fire_pressed: int = 0,
) -> int:
    mem[labels["ZP_JOY_CURR"]] = joy_byte
    mem[labels["ZP_FIRE_PRESSED"]] = fire_pressed
    cyc = _run_subroutine(mpu, labels["HERO_UPDATE"])
    model.step(joy_byte, fire_pressed)
    assert mem[labels["ZP_HERO_X"]] == model.x
    assert mem[labels["ZP_HERO_Y"]] == model.y
    assert mem[labels["ZP_HERO_STATE"]] == model.state
    assert mem[labels["ZP_HERO_FACING"]] == model.facing
    assert mem[labels["ZP_HERO_ANIM_SET"]] == model.anim_set
    assert mem[labels["ZP_HERO_ANIM_FRAME"]] == model.anim_frame
    assert mem[labels["ZP_HERO_ANIM_TIMER"]] == model.anim_timer
    assert mem[labels["ZP_HERO_FALL_IDX"]] == model.fall_idx
    assert mem[labels["ZP_HERO_JUMP_IDX"]] == model.jump_idx
    assert mem[labels["ZP_HERO_JUMP_DIR"]] == model.jump_dir
    assert mem[labels["ZP_HERO_WALK_SUB"]] == model.walk_sub
    assert mem[labels["ZP_HERO_FELL_OUT"]] == model.fell_out
    assert mem[labels["ZP_FIRE_PRESSED"]] == model.fire_pressed
    assert mem[labels["ZP_HERO_DIRTY"]] == 0
    if model.fell_out == 0:
        _assert_pmg_clean(
            mem,
            labels,
            x_cc=model.x,
            y_pmg=model.y,
            anim_set=model.anim_set,
            anim_frame=model.anim_frame,
        )
    return cyc


# ---------------------------------------------------------------------------
# 1. Build-Time Validation & room_draw Ladder Map Parity
# ---------------------------------------------------------------------------


def test_ladder_tag_rejected_on_blockable_object(tmp_path: Path) -> None:
    """Build-time validation rejects a blockable object carrying the 'ladder' tag."""
    doc: dict[str, Any] = yaml.safe_load(ROOMS_YAML.read_text(encoding="utf-8"))
    bad_doc = copy.deepcopy(doc)
    for obj in bad_doc["objects"]:
        if "ladder" in (obj.get("tags") or []):
            obj["non-blockable"] = False
            break
    else:
        pytest.fail("Expected at least one object with tag 'ladder' in rooms.yaml")

    bad_yaml = tmp_path / "bad_ladder.yaml"
    bad_yaml.write_text(yaml.safe_dump(bad_doc, sort_keys=False), encoding="utf-8")
    # Point image path to existing images/ directory via symlink or relative path
    for grp in bad_doc["object_groups"]:
        img_rel = grp.get("image")
        if img_rel:
            dst = tmp_path / img_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((ROOT_DIR / img_rel).read_bytes())

    with pytest.raises(RoomCompileError, match="non-blockable"):
        compile_project(bad_yaml)


def test_room_draw_builds_ladder_map_matching_ssot() -> None:
    """room_draw populates room_ladder_map dynamically matching all 'ladder'-tagged objects in SSOT."""
    mpu, mem, labels = _fresh_emu()
    doc: dict[str, Any] = yaml.safe_load(ROOMS_YAML.read_text(encoding="utf-8"))
    objs = {int(o["id"]): o for o in doc.get("objects", [])}

    for room in doc.get("rooms", []):
        rid = int(room["id"])
        mpu.x = rid
        _run_subroutine(mpu, labels["ROOM_DRAW"])
        actual = _read_bitmap(mem, labels["ROOM_LADDER_MAP"])

        expected = [[False] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        for inst in room.get("placed", []):
            obj = objs[int(inst["object"])]
            if "ladder" not in (obj.get("tags") or []):
                continue
            w = int(obj["frames"][0]["w"])
            h = int(obj["frames"][0]["h"])
            if "repeat-xy" in inst:
                rx_cnt, ry_cnt = int(inst["repeat-xy"][0]), int(inst["repeat-xy"][1])
            else:
                rx_cnt = int(inst.get("repeat-x", 1))
                ry_cnt = int(inst.get("repeat-y", 1))
            ix, iy = int(inst["x"]), int(inst["y"])
            for ry in range(ry_cnt):
                for rx in range(rx_cnt):
                    for dy in range(h):
                        for dx in range(w):
                            cx = ix + rx * w + dx
                            cy = iy + ry * h + dy
                            if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                                expected[cy][cx] = True

        assert actual == expected, f"room_ladder_map mismatch in room {rid}"


# ---------------------------------------------------------------------------
# 2. Walking on Ladder Top Rung Without Falling
# ---------------------------------------------------------------------------


def test_walk_across_ladder_top_rung_without_falling() -> None:
    """Hero walks from bricks onto ladder top rung and across to bricks without falling."""
    mpu, mem, labels = _fresh_emu()
    # Floor at row 10 cols 0..9 and 13..25; ladder cols 10..12 rows 10..16
    block = _build_grid(rects=[(0, 9, 10, 10), (13, 25, 10, 10)])
    ladder = _build_grid(rects=[(10, 12, 10, 16)])
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=8, start_y_cell=9)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 8, 9)

    start_y = model.y
    # Walk right all the way across ladder (cols 10..12) onto bricks at col 14
    for _ in range(90):
        _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
        assert model.state == labels["HERO_STATE_STANDING"]
        assert model.y == start_y
    assert model.x >= 14 * 4

    # Walk back left across ladder onto left bricks
    for _ in range(90):
        _step_and_check(mpu, mem, labels, model, JOY_LEFT)
        assert model.state == labels["HERO_STATE_STANDING"]
        assert model.y == start_y
    assert model.x <= 8 * 4


# ---------------------------------------------------------------------------
# 3. Descending, Stopping on Release, Sideways Column Clamping & Floor Landing
# ---------------------------------------------------------------------------


def test_descend_stop_on_release_sideways_clamped_and_land_on_floor() -> None:
    """Descending stops when DOWN released (0 gravity, 0 redraw), restricts X to ladder cols, and lands on floor."""
    mpu, mem, labels = _fresh_emu()
    # Top floor at row 6 (gap cols 10..12 for ladder), bottom floor at row 14 (cols 0..39),
    # wall right beside ladder at col 9 rows 7..13
    block = _build_grid(
        rects=[(0, 9, 6, 6), (13, 39, 6, 6), (0, 39, 14, 14), (9, 9, 7, 13)]
    )
    ladder = _build_grid(rects=[(10, 12, 6, 13)])
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=10, start_y_cell=5)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 10, 5)

    # Descend 12 frames -> in ON_LADDER
    for _ in range(12):
        _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_ON_LADDER"]
    assert model.anim_set == labels["HERO_UP_DOWN"]
    mid_y = model.y

    # Release DOWN -> stops on current rung, gravity disabled, 0 PMG writes
    for _ in range(10):
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
        assert model.state == labels["HERO_STATE_ON_LADDER"]
        assert model.y == mid_y

    # Move RIGHT while descending -> clamped to right edge of ladder (col 12 -> max x = 11*4 = 44)
    for _ in range(24):
        _step_and_check(mpu, mem, labels, model, JOY_DOWN_RIGHT)
    assert model.x == 11 * 4  # cols 11..12 (within 10..12)

    # Move LEFT while stationary on rung -> clamped to left edge of ladder (col 10 -> min x = 10*4 = 40, also wall at col 9)
    for _ in range(24):
        _step_and_check(mpu, mem, labels, model, JOY_LEFT)
    assert model.x == 10 * 4  # cols 10..11 (cannot enter wall col 9)

    # Continue descending until landing on blockable floor at row 14
    for _ in range(80):
        _step_and_check(mpu, mem, labels, model, JOY_DOWN)
        if model.state == labels["HERO_STATE_STANDING"]:
            break
    assert model.state == labels["HERO_STATE_STANDING"]
    assert model.y == 14 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]


# ---------------------------------------------------------------------------
# 4. Ascending, Top Rung Exit & Stacked Ladder Continuity
# ---------------------------------------------------------------------------


def test_ascend_stacked_ladders_stop_on_top_rung_and_walk() -> None:
    """Hero climbs stacked ladders continuously, stops on top rung in STANDING, and walks along it."""
    mpu, mem, labels = _fresh_emu()
    # Bottom floor at row 16; two stacked ladder segments: rows 12..15 + rows 8..11 (cols 15..17)
    block = _build_grid(rects=[(0, 39, 16, 16), (12, 14, 8, 8), (18, 20, 8, 8)])
    ladder = _build_grid(rects=[(15, 17, 12, 15), (15, 17, 8, 11)])
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=15, start_y_cell=15)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 15, 15)
    assert model.state == labels["HERO_STATE_STANDING"]

    # Hold UP to climb all the way past the seam (row 12) up to top rung (row 8)
    for _ in range(80):
        _step_and_check(mpu, mem, labels, model, JOY_UP)
        if model.y == 8 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"] and model.state == labels["HERO_STATE_STANDING"]:
            break
    assert model.state == labels["HERO_STATE_STANDING"]
    assert model.y == 8 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]

    # Holding UP further at top rung must NOT climb into empty air
    for _ in range(10):
        _step_and_check(mpu, mem, labels, model, JOY_UP)
        assert model.state == labels["HERO_STATE_STANDING"]
        assert model.y == 8 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]

    # Walk right along top rung onto adjacent bricks at col 18
    for _ in range(40):
        _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
        assert model.state == labels["HERO_STATE_STANDING"]
    assert model.x >= 18 * 4


# ---------------------------------------------------------------------------
# 5. Jumping From a Ladder (Top, Middle, Bottom) with FIRE
# ---------------------------------------------------------------------------


def test_jump_from_ladder_with_fire_at_top_middle_and_bottom() -> None:
    """Pressing FIRE on a ladder (top rung, mid-ladder, bottom) consumes FIRE and launches a normal jump."""
    mpu, mem, labels = _fresh_emu()
    block = _build_grid(rects=[(0, 39, 18, 18)])
    ladder = _build_grid(rects=[(15, 17, 10, 17)])

    # A) Jump from TOP rung with FIRE + RIGHT
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=15, start_y_cell=9)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 15, 9)
    assert model.state == labels["HERO_STATE_STANDING"]
    _step_and_check(mpu, mem, labels, model, JOY_RIGHT, fire_pressed=1)
    assert model.state == labels["HERO_STATE_JUMPING"]
    assert model.jump_dir == labels["HERO_FACING_RIGHT"]
    assert mem[labels["ZP_FIRE_PRESSED"]] == 0

    # B) Jump from MIDDLE of ladder while descending with FIRE + LEFT
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=15, start_y_cell=9)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 15, 9)
    for _ in range(20):
        _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_ON_LADDER"]
    y_before_jump = model.y
    _step_and_check(mpu, mem, labels, model, JOY_LEFT, fire_pressed=1)
    assert model.state == labels["HERO_STATE_JUMPING"]
    assert model.jump_dir == labels["HERO_FACING_LEFT"]
    assert model.y < y_before_jump
    assert mem[labels["ZP_FIRE_PRESSED"]] == 0

    # C) Jump from BOTTOM of ladder while climbing with FIRE (no direction -> uses facing)
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=15, start_y_cell=17)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 15, 17)
    for _ in range(4):
        _step_and_check(mpu, mem, labels, model, JOY_UP)
    assert model.state == labels["HERO_STATE_ON_LADDER"]
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE, fire_pressed=1)
    assert model.state == labels["HERO_STATE_JUMPING"]
    assert model.jump_dir == model.facing
    assert mem[labels["ZP_FIRE_PRESSED"]] == 0


# ---------------------------------------------------------------------------
# 6. Landing on a Ladder After a Jump & Grabbing Mid-Jump with UP
# ---------------------------------------------------------------------------


def test_land_on_ladder_from_jump_and_grab_mid_jump_with_up() -> None:
    """Jumping onto a ladder lands on a rung; UP+RIGHT passes through while rising, pure UP latches mid-air."""
    mpu, mem, labels = _fresh_emu()
    # Platform on left at row 14 (cols 4..10); ladder at cols 13..15 rows 8..17; bottom floor row 18
    block = _build_grid(rects=[(4, 10, 14, 14), (0, 39, 18, 18)])
    ladder = _build_grid(rects=[(13, 15, 8, 17)])

    # A) Jump RIGHT from col 9 onto ladder -> lands on a ladder rung in STANDING
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=9, start_y_cell=13)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 9, 13)
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    assert model.state == labels["HERO_STATE_JUMPING"]
    landed = False
    for _ in range(40):
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
        if model.state == labels["HERO_STATE_STANDING"]:
            landed = True
            break
    assert landed
    assert model.ladder_under_feet()
    assert model.y < 18 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]

    # B) Jump RIGHT across ladder holding UP+RIGHT -> passes through while rising;
    #    switching to pure UP once overlapping ladder latches immediately into ON_LADDER!
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=10, start_y_cell=13)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 10, 13)
    for _ in range(6):
        _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    assert model.state == labels["HERO_STATE_JUMPING"]
    assert model.ladder_behind()  # Overlapping ladder while rising, did NOT latch on UP+RIGHT

    # Switch to pure UP -> grabs ladder mid-jump!
    _step_and_check(mpu, mem, labels, model, JOY_UP)
    assert model.state == labels["HERO_STATE_ON_LADDER"]
    assert model.anim_set == labels["HERO_UP_DOWN"]


# ---------------------------------------------------------------------------
# 7. Edge Cases: Screen Edges, Hanging Ladder Fall-Off & Cycle Budget
# ---------------------------------------------------------------------------


def test_ladder_at_screen_edges_hanging_falloff_and_cycle_budget() -> None:
    """Verify ladders at col 0 / col 39, hanging ladder fall-off, and PAL cycle budget."""
    mpu, mem, labels = _fresh_emu()
    # Hanging ladder at left screen edge (cols 0..2, rows 0..3) and right edge (cols 37..39, rows 4..6)
    block = _build_grid(rects=[(0, 39, 20, 20)])
    ladder = _build_grid(rects=[(0, 2, 0, 3), (37, 39, 4, 6)])

    # Left screen edge ladder: clamp X >= 0, clamp Y >= HERO_MIN_PMG_Y, descend past row 3 -> FALLING
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=0, start_y_cell=1)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 0, 1)
    # Grab ladder from falling with pure UP
    _step_and_check(mpu, mem, labels, model, JOY_UP)
    assert model.state == labels["HERO_STATE_ON_LADDER"]

    max_cyc = 0
    # Climb up to top of screen (clamps at HERO_MIN_PMG_Y)
    for _ in range(16):
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, JOY_UP))
    assert model.y >= labels["HERO_MIN_PMG_Y"]

    # Try moving left at col 0 -> stays clamped at 0
    for _ in range(6):
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, JOY_LEFT))
    assert model.x == 0

    # Descend past bottom of hanging ladder (row 3) -> transitions to FALLING
    for _ in range(40):
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, JOY_DOWN))
        if model.state == labels["HERO_STATE_FALLING"]:
            break
    assert model.state == labels["HERO_STATE_FALLING"]

    # Right screen edge ladder (cols 37..39, rows 4..6): clamp X <= HERO_MAX_X_CC (152)
    _init_hero(mpu, mem, labels, block, ladder, start_x_cell=38, start_y_cell=3)
    model = HeroLadderModel.from_emu(mem, labels, block, ladder, 38, 3)
    assert model.state == labels["HERO_STATE_STANDING"]
    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_ON_LADDER"]
    for _ in range(12):
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, JOY_RIGHT))
    assert model.x == labels["HERO_MAX_X_CC"]
    assert max_cyc < 3000, f"Ladder update took {max_cyc} cycles (exceeds safe PAL budget)"
