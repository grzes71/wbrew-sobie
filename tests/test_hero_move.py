"""Comprehensive pytest + py65 tests for Hero (Player 0) walk, jump, squat & collision."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"

ROOM_WIDTH = 40
ROOM_HEIGHT = 24
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


def _build_block_grid(
    *,
    floors: list[tuple[int, int, int]] | None = None,
    cells: list[tuple[int, int]] | None = None,
) -> list[list[bool]]:
    """Build a synthetic 40x24 blocking bitmap: floors=(row, col_a, col_b), cells=(col, row)."""
    grid = [[False] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
    for row, col_a, col_b in floors or []:
        for col in range(col_a, col_b + 1):
            grid[row][col] = True
    for col, row in cells or []:
        grid[row][col] = True
    return grid


def _poke_block_map(mem: bytearray | ObservableMemory, bmap_addr: int, grid: list[list[bool]]) -> None:
    for i in range(ROOM_HEIGHT * 5):
        mem[bmap_addr + i] = 0
    for r in range(ROOM_HEIGHT):
        row_base = bmap_addr + r * 5
        for c in range(ROOM_WIDTH):
            if grid[r][c]:
                mem[row_base + (c >> 3)] |= 0x80 >> (c & 7)


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


def _init_hero_on_grid(
    mpu: MPU,
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    grid: list[list[bool]],
    start_x_cell: int,
    start_y_cell: int,
    joy: int = JOY_CENTRE,
) -> None:
    _poke_block_map(mem, labels["ROOM_BLOCK_MAP"], grid)
    mem[labels["ZP_JOY_CURR"]] = joy
    mpu.x = start_x_cell
    mpu.y = start_y_cell
    _run_subroutine(mpu, labels["HERO_INIT"])


@dataclass
class HeroModel:
    """Reference Python model mirroring 6502 hero physics, collision, and animation."""

    grid: list[list[bool]]
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

    @classmethod
    def from_emu(
        cls,
        mem: bytearray | ObservableMemory,
        labels: dict[str, int],
        grid: list[list[bool]],
        start_x_cell: int,
        start_y_cell: int,
    ) -> "HeroModel":
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
            grid=grid,
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

    def row_range_blocked(self, row: int, col_a: int, col_b: int) -> bool:
        if row >= ROOM_HEIGHT or col_a >= ROOM_WIDTH:
            return False
        cb = min(ROOM_WIDTH - 1, col_b)
        if cb < col_a:
            return False
        return any(self.grid[row][c] for c in range(col_a, cb + 1))

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
        return any(self.grid[r][c] for c in range(col_l, min(ROOM_WIDTH - 1, col_r) + 1) for r in range(top_row, bot_row + 1))

    def check_support(self) -> bool:
        bottom_pf = self.y - self.labels["HERO_TOP_TO_PF_BOTTOM"]
        if (bottom_pf & 7) != 0:
            return False
        row = bottom_pf >> 3
        col_l, col_r = self.footprint_cols()
        return self.row_range_blocked(row, col_l, col_r)

    def try_step_x(self, direction: int, step_cc: int) -> bool:
        w = self.labels["HERO_COLLISION_WIDTH_CC"]
        max_x = self.labels["HERO_MAX_X_CC"]
        if direction == self.labels["HERO_FACING_RIGHT"]:
            cand = min(max_x, self.x + step_cc)
        else:
            cand = max(0, self.x - step_cc)
        if cand == self.x:
            return False
        if not self.blocked_at(cand, self.y):
            self.x = cand
            self.dirty = 1
            return True
        if step_cc < 2:
            return False
        if direction == self.labels["HERO_FACING_RIGHT"]:
            flush = ((cand + w - 1) & 0xFC) - w
            if flush <= self.x:
                return False
        else:
            flush = (cand & 0xFC) + 4
            if flush >= self.x:
                return False
        if not self.blocked_at(flush, self.y):
            self.x = flush
            self.dirty = 1
            return True
        return False

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
        self.anim_frame += 1
        if self.anim_frame >= self.set_counts[self.anim_set]:
            self.anim_frame = 0
        self.dirty = 1

    def tick_walk_anim(self) -> None:
        self.anim_timer -= 1
        if self.anim_timer != 0:
            return
        self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
        self.anim_frame += 1
        if self.anim_frame >= self.set_counts[self.anim_set]:
            self.anim_frame = 0
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

    @staticmethod
    def read_input(joy_byte: int) -> int:
        tbl = {
            0x05: 5,  # SQUAT_RIGHT
            0x06: 3,  # JUMP_RIGHT
            0x07: 1,  # WALK_RIGHT
            0x09: 6,  # SQUAT_LEFT
            0x0A: 4,  # JUMP_LEFT
            0x0B: 2,  # WALK_LEFT
            0x0D: 7,  # SQUAT (DOWN only, keep facing)
        }
        return tbl.get(joy_byte & 0x0F, 0)

    def step(self, joy_byte: int) -> None:
        self.dirty = 0
        if self.state == self.labels["HERO_STATE_STANDING"]:
            if not self.check_support():
                self.enter_falling()
                self.dirty = 0
                return
            cmd = self.read_input(joy_byte)
            if cmd == 0:
                self.walk_sub = 0
                if self.anim_set != self.stand_set_for(self.facing) or self.anim_frame != self.labels["HERO_STAND_FRAME"]:
                    self.enter_standing()
            elif cmd in (1, 2):
                self.facing = cmd - 1
                tset = self.stand_set_for(self.facing)
                if self.anim_set != tset:
                    self.anim_set = tset
                    self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
                    self.anim_frame = self.labels["HERO_STAND_FRAME"]
                    self.walk_sub = 0
                    self.dirty = 1
                if self.walk_sub != 0:
                    self.walk_sub -= 1
                    self.tick_walk_anim()
                else:
                    self.walk_sub = self.labels["HERO_WALK_SPEED_SUBSTEPS"] - 1
                    if self.try_step_x(self.facing, self.labels["HERO_WALK_STEP_CC"]):
                        self.tick_walk_anim()
                        if not self.check_support():
                            self.enter_falling()
                    else:
                        self.walk_sub = 0
                        if self.anim_frame != self.labels["HERO_STAND_FRAME"]:
                            self.anim_timer = self.labels["HERO_WALK_ANIM_TICKS"]
                            self.anim_frame = self.labels["HERO_STAND_FRAME"]
                            self.dirty = 1
            elif cmd in (3, 4):
                self.facing = cmd - 3
                self.jump_dir = self.facing
                self.anim_set = self.jump_set_for(self.facing)
                self.anim_timer = self.set_durs[self.anim_set]
                self.anim_frame = 0
                self.jump_idx = 0
                self.walk_sub = 0
                self.state = self.labels["HERO_STATE_JUMPING"]
                self.dirty = 1
                self._step_jump()
            else:
                if cmd != self.labels["HERO_CMD_SQUAT"]:
                    self.facing = cmd - 5
                self.anim_set = self.squat_set_for(self.facing)
                self.anim_timer = self.set_durs[self.anim_set]
                self.anim_frame = 0
                self.walk_sub = 0
                self.state = self.labels["HERO_STATE_SQUATTING"]
                self.dirty = 1
        elif self.state == self.labels["HERO_STATE_FALLING"]:
            self._step_fall()
        elif self.state == self.labels["HERO_STATE_JUMPING"]:
            self._step_jump()
        else:
            self._step_squat(joy_byte)
        self.dirty = 0

    def _step_jump(self) -> None:
        min_y = self.labels["HERO_MIN_PMG_Y"]
        top_pf = self.labels["PLAYFIELD_TOP_PMG_Y"]
        if self.jump_idx >= len(self.jump_steps) or self.y <= min_y:
            self.state = self.labels["HERO_STATE_FALLING"]
            self.fall_idx = 0
        else:
            step = self.jump_steps[self.jump_idx]
            self.jump_idx += 1
            cand_y = self.y - step
            hit_top = cand_y < min_y
            if hit_top:
                cand_y = min_y
            old_head = (self.y - top_pf) >> 3
            new_head = (cand_y - top_pf) >> 3
            col_l, col_r = self.footprint_cols()
            if new_head != old_head and self.row_range_blocked(new_head, col_l, col_r):
                snapped = ((new_head + 1) << 3) + top_pf
                if snapped != self.y:
                    self.y = snapped
                    self.dirty = 1
                self.state = self.labels["HERO_STATE_FALLING"]
                self.fall_idx = 0
            else:
                self.y = cand_y
                self.dirty = 1
                if hit_top or self.jump_idx >= len(self.jump_steps):
                    self.state = self.labels["HERO_STATE_FALLING"]
                    self.fall_idx = 0

        if self.jump_dir < 0x80:
            self.try_step_x(self.jump_dir, self.labels["HERO_JUMP_SPEED_CC"])
        self.tick_anim()

    def _step_fall(self) -> None:
        if self.jump_dir < 0x80:
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
            if self.row_range_blocked(new_row, col_l, col_r):
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
        if cmd < 5:
            self.enter_standing()
            return
        if cmd != self.labels["HERO_CMD_SQUAT"]:
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


def _assert_matches_model(
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    model: HeroModel,
) -> None:
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


def _step_and_check(
    mpu: MPU,
    mem: bytearray | ObservableMemory,
    labels: dict[str, int],
    model: HeroModel,
    joy_byte: int,
) -> int:
    mem[labels["ZP_JOY_CURR"]] = joy_byte
    cyc = _run_subroutine(mpu, labels["HERO_UPDATE"])
    model.step(joy_byte)
    _assert_matches_model(mem, labels, model)
    return cyc


# ---------------------------------------------------------------------------
# 1. Collision Helpers & Input Decoding
# ---------------------------------------------------------------------------


def test_col_range_blocked_and_hero_blocked_at() -> None:
    """Verify col_range_blocked (bounds, clamping, reversed range) & hero_blocked_at row spans."""
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(cells=[(5, 4), (5, 10), (39, 23)])
    _poke_block_map(mem, labels["ROOM_BLOCK_MAP"], grid)

    for col, ra, rb, exp in (
        (5, 0, 3, False),
        (5, 0, 4, True),
        (5, 4, 4, True),
        (5, 5, 9, False),
        (5, 5, 10, True),
        (5, 10, 8, False),   # row_b < row_a -> unblocked
        (5, 22, 30, False),  # row_b clamped to 23
        (39, 22, 30, True),  # clamped row_b catches row 23
        (40, 0, 23, False),  # col >= 40 -> unblocked
        (5, 24, 25, False),  # row_a >= 24 -> unblocked
    ):
        mpu.x = col
        mpu.a = ra
        mpu.y = rb
        _run_subroutine(mpu, labels["COL_RANGE_BLOCKED"])
        assert ((mpu.p & 0x01) != 0) == exp
        assert (mpu.a != 0) == exp

    # Standing at cell y=10 (top_pmg = 11*8+14 = 102, body covers PF rows 8..10 = [102..119]):
    # cell (5, 10) must block col 4..5, while row 11 (support) below feet must NOT block!
    grid2 = _build_block_grid(floors=[(11, 0, 39)], cells=[(12, 8), (16, 9), (20, 10), (24, 7)])
    _poke_block_map(mem, labels["ROOM_BLOCK_MAP"], grid2)

    y_row10 = 11 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]  # 102: PF [70..87] -> rows 8..10
    # Wait: top_pf = 102 - 32 = 70 (row 8), last_pf = 102 - 15 = 87 (row 10)
    # 102 mod 8 -> 102 - 14 = 88 -> support row 11 (floors[(11, 0, 39)] must NOT cause blocked_at=True)
    assert not _assert_blocked(mpu, labels, x_cc=4, y_pmg=y_row10)
    assert _assert_blocked(mpu, labels, x_cc=11 * 4, y_pmg=y_row10)  # touches (12, 8) -> head row
    assert _assert_blocked(mpu, labels, x_cc=15 * 4, y_pmg=y_row10)  # touches (16, 9) -> mid row
    assert _assert_blocked(mpu, labels, x_cc=19 * 4, y_pmg=y_row10)  # touches (20, 10) -> foot row
    assert not _assert_blocked(mpu, labels, x_cc=23 * 4, y_pmg=y_row10)  # (24, 7) is above head -> free

    # Mid-stride y spanning 4 rows: y_pmg = 99 (top_pf = 67 -> row 8, last_pf = 84 -> row 10; 103 -> 71..88 -> rows 8..11)
    y_4rows = 103  # top_pf = 71 (row 8), last_pf = 88 (row 11 -> floor at row 11 overlaps!)
    assert _assert_blocked(mpu, labels, x_cc=4, y_pmg=y_4rows)

    # Top of screen y=26 (partially above playfield top=32): clamps top_row=0, checks rows 0..1
    grid3 = _build_block_grid(cells=[(3, 0)])
    _poke_block_map(mem, labels["ROOM_BLOCK_MAP"], grid3)
    assert _assert_blocked(mpu, labels, x_cc=8, y_pmg=26)  # cols 2..3, rows 0..1


def _assert_blocked(mpu: MPU, labels: dict[str, int], *, x_cc: int, y_pmg: int) -> bool:
    mpu.x = x_cc
    mpu.a = y_pmg
    _run_subroutine(mpu, labels["HERO_BLOCKED_AT"])
    return (mpu.p & 0x01) != 0


def test_hero_read_input_all_16_joystick_states() -> None:
    """All 16 zp_joy_curr values map deterministically without undefined states."""
    mpu, mem, labels = _fresh_emu()
    for joy in range(16):
        mem[labels["ZP_JOY_CURR"]] = joy
        _run_subroutine(mpu, labels["HERO_READ_INPUT"])
        assert mpu.a == HeroModel.read_input(joy)


# ---------------------------------------------------------------------------
# 2. Walking, Wall Stops, Body-Row Checks & Screen Edges
# ---------------------------------------------------------------------------


def test_walk_left_right_speed_facing_animation_and_model() -> None:
    """Walking advances step_cc every substeps frames, advances anim on move ticks, and resets phase on stop/turn."""
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(12, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=10, start_y_cell=11)
    model = HeroModel.from_emu(mem, labels, grid, 10, 11)
    _assert_matches_model(mem, labels, model)

    step_cc = labels["HERO_WALK_STEP_CC"]
    substeps = labels["HERO_WALK_SPEED_SUBSTEPS"]
    anim_ticks = labels["HERO_WALK_ANIM_TICKS"]
    assert step_cc == 1 and substeps == 3 and anim_ticks == 5  # 1/3 cc/frame, 5 PAL ticks/frame

    # Walk right over N = 24 frames (multiple of substeps=3) -> exactly 8 cc, moving immediately on frame 0
    n_even = 24
    start_x = model.x
    xs: list[int] = []
    frames_anim: list[int] = []
    for _ in range(n_even):
        _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
        xs.append(model.x - start_x)
        frames_anim.append(model.anim_frame)

    expected_disp = ((n_even + substeps - 1) // substeps) * step_cc
    assert model.x == start_x + expected_disp == start_x + n_even // substeps
    assert xs[0] == step_cc and xs[1] == step_cc  # Frame 0 steps immediately; frame 1 waits
    assert model.facing == labels["HERO_FACING_RIGHT"]
    assert model.anim_set == labels["HERO_WALK_RIGHT"]
    # Animation frame changes strictly every HERO_WALK_ANIM_TICKS frames
    assert frames_anim[anim_ticks - 2] == 0 and frames_anim[anim_ticks - 1] == 1

    # Stop during wait phase (after odd 1 step -> walk_sub == 1) resets phase so next press moves immediately
    x_mid = model.x
    _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
    assert model.x == x_mid + step_cc and model.walk_sub == substeps - 1
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    assert model.walk_sub == 0
    assert model.anim_frame == labels["HERO_STAND_FRAME"]
    _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
    assert model.x == x_mid + 2 * step_cc  # Moves immediately on resume!

    # Reversing direction mid-wait-frame (while walk_sub == substeps - 1) resets phase and moves left on tick 1
    assert model.walk_sub == substeps - 1
    x_turn = model.x
    _step_and_check(mpu, mem, labels, model, JOY_LEFT)
    assert model.x == x_turn - step_cc
    assert model.facing == labels["HERO_FACING_LEFT"]
    assert model.anim_set == labels["HERO_WALK_LEFT"]

    # Walk left for remaining odd N = 7 frames -> exact ((N + substeps - 1) // substeps) * step_cc
    n_odd = 7
    x_odd0 = model.x
    for _ in range(n_odd):
        _step_and_check(mpu, mem, labels, model, JOY_LEFT)
    # Note model.walk_sub was substeps - 1 entering n_odd loop
    assert model.x == x_odd0 - (n_odd // substeps) * step_cc

    # Stop cleanly, UP-only stands still preserving facing
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    x_idle = model.x
    _step_and_check(mpu, mem, labels, model, JOY_UP)
    assert model.x == x_idle and model.anim_frame == 0 and model.facing == labels["HERO_FACING_LEFT"]


def test_walk_wall_collision_all_body_rows_and_flush_clamp() -> None:
    """Walls at head-only, mid-only, or foot-only row block both directions; step>1 clamps flush."""
    substeps = _fresh_emu()[2]["HERO_WALK_SPEED_SUBSTEPS"]
    # Hero standing on row 12 sits at cell y=11 -> body overlaps PF rows 9, 10, 11 (row 8 is above head!)
    for obs_row in (9, 10, 11):
        mpu, mem, labels = _fresh_emu()
        # Walls at col 7 (left) and col 15 (right)
        grid = _build_block_grid(floors=[(12, 0, 39)], cells=[(7, obs_row), (15, obs_row)])
        _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=10, start_y_cell=11)
        model = HeroModel.from_emu(mem, labels, grid, 10, 11)

        # Walk right until touching col 15 flush: col 15 starts at cc 60 -> hero right edge at 59 -> x = 52
        for _ in range(20 * substeps):
            _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
        assert model.x == 15 * 4 - labels["HERO_COLLISION_WIDTH_CC"]
        assert model.anim_frame == labels["HERO_STAND_FRAME"]
        assert model.walk_sub == 0

        # Walk left until touching col 7 flush: col 7 ends at cc 31 -> hero left edge at 32 -> x = 32
        for _ in range(30 * substeps):
            _step_and_check(mpu, mem, labels, model, JOY_LEFT)
        assert model.x == (7 + 1) * 4
        assert model.anim_frame == labels["HERO_STAND_FRAME"]
        assert model.walk_sub == 0

    # Verify step > 1 flush clamp via direct hero_try_step_x(Y=3) call
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(12, 0, 39)], cells=[(14, 10), (6, 10)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=10, start_y_cell=11)
    # Flush right against col 14 is x = 14*4 - 8 = 48. Start at x = 46 and step right by 3 (46+3=49 blocked -> flush 48!)
    mem[labels["ZP_HERO_X"]] = 46
    mpu.a = labels["HERO_FACING_RIGHT"]
    mpu.y = 3
    _run_subroutine(mpu, labels["HERO_TRY_STEP_X"])
    assert (mpu.p & 0x01) != 0 and mem[labels["ZP_HERO_X"]] == 48

    # Second step by 3 at flush x=48 returns C=0 (no move)
    mpu.a = labels["HERO_FACING_RIGHT"]
    mpu.y = 3
    _run_subroutine(mpu, labels["HERO_TRY_STEP_X"])
    assert (mpu.p & 0x01) == 0 and mem[labels["ZP_HERO_X"]] == 48

    # Flush left against col 6 is x = (6+1)*4 = 28. Start at x = 30 and step left by 3 (30-3=27 blocked -> flush 28!)
    mem[labels["ZP_HERO_X"]] = 30
    mpu.a = labels["HERO_FACING_LEFT"]
    mpu.y = 3
    _run_subroutine(mpu, labels["HERO_TRY_STEP_X"])
    assert (mpu.p & 0x01) != 0 and mem[labels["ZP_HERO_X"]] == 28


def test_screen_edges_clamp_no_wrap_or_underflow() -> None:
    """Walking past x=0 and x=HERO_MAX_X_CC clamps cleanly with no wrap, no Game Over, and zero dirty when settled."""
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(10, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=1, start_y_cell=9)
    model = HeroModel.from_emu(mem, labels, grid, 1, 9)
    substeps = labels["HERO_WALK_SPEED_SUBSTEPS"]

    for _ in range(15 * substeps):
        _step_and_check(mpu, mem, labels, model, JOY_LEFT)
    assert model.x == 0
    assert model.fell_out == 0
    assert model.state == labels["HERO_STATE_STANDING"]

    # Pressing left at x=0 leaves PMG untouched (zero writes)
    om = ObservableMemory(subject=mem)
    mpu_obs = MPU(memory=om)
    mpu_obs.reset()
    writes: list[int] = []
    om.subscribe_to_write(range(labels["PMG_P0"], labels["PMG_P0"] + 256), lambda a, _v: writes.append(a))
    om.subscribe_to_write([HPOSP0], lambda a, _v: writes.append(a))
    mem[labels["ZP_JOY_CURR"]] = JOY_LEFT
    _run_subroutine(mpu_obs, labels["HERO_UPDATE"])
    assert writes == [] and mem[labels["ZP_HERO_X"]] == 0

    # Walk to right edge near x = HERO_MAX_X_CC (152 -> cell col 38)
    mem[labels["ZP_HERO_X"]] = labels["HERO_MAX_X_CC"] - 4
    model.x = labels["HERO_MAX_X_CC"] - 4
    for _ in range(15 * substeps):
        _step_and_check(mpu, mem, labels, model, JOY_RIGHT)
    assert model.x == labels["HERO_MAX_X_CC"]
    assert model.x + labels["HERO_COLLISION_WIDTH_CC"] == 160
    assert model.fell_out == 0


# ---------------------------------------------------------------------------
# 3. Walking Off a Ledge -> Falling & Landing
# ---------------------------------------------------------------------------


def test_walk_off_ledge_falls_ignores_air_input_and_lands() -> None:
    """Stepping off a platform edge starts vertical FALLING, ignores air input, and lands facing preserved."""
    mpu, mem, labels = _fresh_emu()
    # Upper platform rows 6 cols 0..9; lower floor row 12 cols 0..39
    grid = _build_block_grid(floors=[(6, 0, 9), (12, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=7, start_y_cell=5)
    model = HeroModel.from_emu(mem, labels, grid, 7, 5)

    # Walk right until hero clears col 9 (at x = 40, col_left = 10, col_right = 11)
    while model.state == labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_RIGHT)

    assert model.state == labels["HERO_STATE_FALLING"]
    assert model.anim_set == labels["HERO_FALL"]
    assert model.jump_dir == labels["HERO_JUMP_DIR_NONE"]
    fall_x = model.x

    # Hold conflicting air inputs (LEFT, UP+RIGHT, DOWN+LEFT) while falling -> all ignored!
    air_inputs = [JOY_LEFT, JOY_UP_LEFT, JOY_DOWN_RIGHT, JOY_RIGHT, JOY_CENTRE]
    idx = 0
    while model.state == labels["HERO_STATE_FALLING"]:
        _step_and_check(mpu, mem, labels, model, air_inputs[idx % len(air_inputs)])
        assert model.x == fall_x
        idx += 1

    assert model.state == labels["HERO_STATE_STANDING"]
    assert model.y == 12 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]
    assert model.facing == labels["HERO_FACING_RIGHT"]


# ---------------------------------------------------------------------------
# 4. Jumping (Left & Right, Ceiling, Mid-Air Wall, Top Clamp, No Mid-Air Jump)
# ---------------------------------------------------------------------------


def test_jump_left_and_right_ballistic_arc_and_landing() -> None:
    """UP+RIGHT and UP+LEFT jump with exact step arc, animation, no air steering, and clean landing."""
    for joy_init, exp_dir, exp_set in (
        (JOY_UP_RIGHT, "HERO_FACING_RIGHT", "HERO_JUMP_RIGHT"),
        (JOY_UP_LEFT, "HERO_FACING_LEFT", "HERO_JUMP_LEFT"),
    ):
        mpu, mem, labels = _fresh_emu()
        grid = _build_block_grid(floors=[(15, 0, 39)])
        _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=20, start_y_cell=14)
        model = HeroModel.from_emu(mem, labels, grid, 20, 14)

        start_x = model.x
        start_y = model.y

        # Initiate jump (1st frame rises immediately)
        _step_and_check(mpu, mem, labels, model, joy_init)
        assert model.state == labels["HERO_STATE_JUMPING"]
        assert model.facing == labels[exp_dir]
        assert model.jump_dir == labels[exp_dir]
        assert model.anim_set == labels[exp_set]

        min_y = model.y
        # Hold opposite / squat / centre inputs mid-air -> committed ballistic arc ignores them!
        distractions = [JOY_LEFT, JOY_RIGHT, JOY_DOWN_LEFT, JOY_DOWN_RIGHT, JOY_UP_LEFT, JOY_CENTRE]
        tick = 0
        while model.state != labels["HERO_STATE_STANDING"]:
            _step_and_check(mpu, mem, labels, model, distractions[tick % len(distractions)])
            min_y = min(min_y, model.y)
            tick += 1
            assert tick < 60

        assert start_y - min_y == labels["HERO_JUMP_HEIGHT"]
        assert labels["HERO_JUMP_HEIGHT"] == sum(model.jump_steps) == 27
        expected_dx = (tick + 1) * labels["HERO_JUMP_SPEED_CC"]
        if labels[exp_dir] == labels["HERO_FACING_RIGHT"]:
            assert model.x == start_x + expected_dx
        else:
            assert model.x == start_x - expected_dx
        assert model.y == start_y
        assert model.facing == labels[exp_dir]
        assert model.anim_set == (
            labels["HERO_WALK_RIGHT"] if labels[exp_dir] == labels["HERO_FACING_RIGHT"] else labels["HERO_WALK_LEFT"]
        )


def test_jump_ceiling_wall_mid_arc_and_top_playfield_clamp() -> None:
    """Ceiling stops rise cleanly, mid-arc wall stops X only, top clamp prevents underflow, and no mid-air jump."""
    # 1. Ceiling stop: floor at row 15 (hero y=134, head PF=102 -> row 12); ceiling block at row 11 cols 19..22!
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(15, 0, 39), (11, 19, 22)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=20, start_y_cell=14)
    model = HeroModel.from_emu(mem, labels, grid, 20, 14)
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    # After first rise step (4 lines): 134 -> 130 (PF 98 -> row 12). Second step (3 lines): 127 (PF 95 -> row 11 blocked!) -> snaps to 12*8+32 = 128!
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    assert model.y == 12 * 8 + labels["PLAYFIELD_TOP_PMG_Y"]  # 128
    assert model.state == labels["HERO_STATE_FALLING"]
    assert model.fall_idx == 0
    while model.state != labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    assert model.y == 15 * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]

    # 2. Side wall mid-arc stops X only while full vertical arc continues
    mpu, mem, labels = _fresh_emu()
    # Floor row 15; obstacle col 22 rows 11..13 (in air above floor, blocks mid-jump X, leaves floor clear!)
    grid = _build_block_grid(
        floors=[(15, 0, 39)],
        cells=[(22, 11), (22, 12), (22, 13)],
    )
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=19, start_y_cell=14)  # x=76, col 19..20
    model = HeroModel.from_emu(mem, labels, grid, 19, 14)
    start_y = model.y
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    min_y = model.y
    while model.state != labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
        min_y = min(min_y, model.y)
    assert start_y - min_y == labels["HERO_JUMP_HEIGHT"]
    assert model.x == 22 * 4 - labels["HERO_COLLISION_WIDTH_CC"]  # Stopped flush at col 22 (80)
    assert model.y == start_y

    # 3. Top of playfield clamp when jumping near row 3 -> clamps at HERO_MIN_PMG_Y (32), never underflows
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(3, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=15, start_y_cell=2)  # y = 3*8+14 = 38
    model = HeroModel.from_emu(mem, labels, grid, 15, 2)
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)  # 38-4=34
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)  # 34-3=31 -> clamped to 32 & FALLING!
    assert model.y == labels["HERO_MIN_PMG_Y"] == 32
    assert model.state == labels["HERO_STATE_FALLING"]
    while model.state != labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)

    # 4. Jumping at screen edge clamps X cleanly
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(15, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=0, start_y_cell=14)
    model = HeroModel.from_emu(mem, labels, grid, 0, 14)
    _step_and_check(mpu, mem, labels, model, JOY_UP_LEFT)
    while model.state != labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_UP_LEFT)
    assert model.x == 0

    # 5. Cannot re-trigger jump while already FALLING (stepped off ledge)
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(18, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=10, start_y_cell=5)
    model = HeroModel.from_emu(mem, labels, grid, 10, 5)
    assert model.state == labels["HERO_STATE_FALLING"]
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    assert model.state == labels["HERO_STATE_FALLING"] and model.x == 10 * 4


# ---------------------------------------------------------------------------
# 5. Squatting, Idle Fast Path & VBI Cycle Budget
# ---------------------------------------------------------------------------


def test_squat_left_right_animation_and_return_to_standing() -> None:
    """DOWN-only (preserving facing) and DOWN+LEFT/RIGHT crouch in place, switch seamlessly, and ignore air."""
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(12, 0, 39)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=12, start_y_cell=11)
    model = HeroModel.from_emu(mem, labels, grid, 12, 11)
    start_x = model.x
    start_y = model.y

    # 1. DOWN-only from standstill facing RIGHT -> squats facing RIGHT without changing X or facing
    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_SQUATTING"]
    assert model.facing == labels["HERO_FACING_RIGHT"]
    assert model.anim_set == labels["HERO_SQUAT_RIGHT"]
    assert model.x == start_x and model.y == start_y

    # Reach final crouch frame under DOWN-only and verify zero redundant PMG writes
    squat_cnt = mem[labels["HERO_SET_COUNT"] + labels["HERO_SQUAT_RIGHT"]]
    squat_dur = mem[labels["HERO_SET_DUR"] + labels["HERO_SQUAT_RIGHT"]]
    for _ in range(squat_cnt * squat_dur + 2):
        _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.anim_frame == squat_cnt - 1

    om = ObservableMemory(subject=mem)
    mpu_obs = MPU(memory=om)
    mpu_obs.reset()
    writes: list[int] = []
    om.subscribe_to_write(range(labels["PMG_P0"], labels["PMG_P0"] + 256), lambda a, _v: writes.append(a))
    om.subscribe_to_write([HPOSP0], lambda a, _v: writes.append(a))
    for joy in (JOY_DOWN, JOY_DOWN_RIGHT):  # Transition DOWN -> DOWN+RIGHT preserves final frame with 0 redraws
        mem[labels["ZP_JOY_CURR"]] = joy
        _run_subroutine(mpu_obs, labels["HERO_UPDATE"])
        model.step(joy)
    assert writes == []

    # Release to STANDING facing RIGHT
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    assert model.state == labels["HERO_STATE_STANDING"]
    assert model.facing == labels["HERO_FACING_RIGHT"]
    assert model.anim_set == labels["HERO_WALK_RIGHT"]

    # 2. Walk left briefly, then DOWN-only -> squats facing LEFT, X stays fixed; release via UP -> STANDING left
    _step_and_check(mpu, mem, labels, model, JOY_LEFT)
    walk_x = model.x
    _step_and_check(mpu, mem, labels, model, JOY_DOWN_LEFT)
    assert model.state == labels["HERO_STATE_SQUATTING"] and model.x == walk_x
    _step_and_check(mpu, mem, labels, model, JOY_UP)
    assert model.state == labels["HERO_STATE_STANDING"] and model.facing == labels["HERO_FACING_LEFT"]

    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_SQUATTING"]
    assert model.facing == labels["HERO_FACING_LEFT"]
    assert model.anim_set == labels["HERO_SQUAT_LEFT"]
    assert model.x == walk_x

    # Flip to right while squatting and continue holding with DOWN-only
    _step_and_check(mpu, mem, labels, model, JOY_DOWN_RIGHT)
    assert model.facing == labels["HERO_FACING_RIGHT"] and model.anim_set == labels["HERO_SQUAT_RIGHT"]
    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_SQUATTING"] and model.facing == labels["HERO_FACING_RIGHT"]
    _step_and_check(mpu, mem, labels, model, JOY_CENTRE)
    assert model.state == labels["HERO_STATE_STANDING"] and model.anim_set == labels["HERO_WALK_RIGHT"]

    # 3. DOWN-only and DOWN+LEFT/RIGHT are ignored while JUMPING and while FALLING
    _step_and_check(mpu, mem, labels, model, JOY_UP_RIGHT)
    assert model.state == labels["HERO_STATE_JUMPING"]
    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_JUMPING"]
    while model.state != labels["HERO_STATE_FALLING"]:
        _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    _step_and_check(mpu, mem, labels, model, JOY_DOWN)
    assert model.state == labels["HERO_STATE_FALLING"]
    while model.state != labels["HERO_STATE_STANDING"]:
        _step_and_check(mpu, mem, labels, model, JOY_CENTRE)


def test_idle_fast_path_zero_dirty_and_vbi_cycle_budget() -> None:
    """Idle inputs take zero-write fast path; worst-case hero_update fits comfortably in VBI budget."""
    mpu, mem, labels = _fresh_emu()
    grid = _build_block_grid(floors=[(15, 0, 39)], cells=[(15, 14), (10, 10)])
    _init_hero_on_grid(mpu, mem, labels, grid, start_x_cell=12, start_y_cell=14)
    model = HeroModel.from_emu(mem, labels, grid, 12, 14)

    # Idle fast path with ObservableMemory
    om = ObservableMemory(subject=mem)
    mpu_obs = MPU(memory=om)
    mpu_obs.reset()
    writes: list[int] = []
    om.subscribe_to_write(range(labels["PMG_P0"], labels["PMG_P0"] + 256), lambda a, _v: writes.append(a))
    om.subscribe_to_write([HPOSP0], lambda a, _v: writes.append(a))
    for joy in (JOY_CENTRE, JOY_UP):
        mem[labels["ZP_JOY_CURR"]] = joy
        idle_cyc = _run_subroutine(mpu_obs, labels["HERO_UPDATE"])
        assert idle_cyc < 300
    assert writes == []
    assert mem[labels["ZP_HERO_DIRTY"]] == 0

    # Measure cycles across walk, wall stop, jump rise/fall/landing, squat
    max_cyc = 0
    for joy in (
        JOY_RIGHT, JOY_RIGHT, JOY_RIGHT, JOY_RIGHT,
        JOY_LEFT, JOY_LEFT,
        JOY_DOWN, JOY_DOWN_RIGHT, JOY_CENTRE,
        JOY_UP_RIGHT,
    ):
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, joy))
    while model.state != labels["HERO_STATE_STANDING"]:
        max_cyc = max(max_cyc, _step_and_check(mpu, mem, labels, model, JOY_CENTRE))

    # Must fit easily in PAL VBI alongside anim_tick (< 2,500 cycles for hero_update)
    assert max_cyc < 2500, f"Worst-case hero_update took {max_cyc} cycles"
