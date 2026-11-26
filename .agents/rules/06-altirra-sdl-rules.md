---
trigger: always_on
---

# AltirraSDL Emulation & Verification Rules

## 1. Emulator Execution Policy
- **Proactive Verification:** Whenever building, modifying, or testing the game binary (`funky_koval.xex`), verify execution using **AltirraSDL** whenever possible.
- **AltirraSDL Binary Path:**
  `C:\Users\grzes\Documents\Projects\AltirraSDL\build\windows-sdl-release\src\AltirraSDL\Release\AltirraSDL.exe`

## 2. Interactive Run (Visual Verification)
- To launch the emulator for visual/manual testing of the current binary:
  ```powershell
  Start-Process -FilePath "C:\Users\grzes\Documents\Projects\AltirraSDL\build\windows-sdl-release\src\AltirraSDL\Release\AltirraSDL.exe" -ArgumentList "funky_koval.xex"
  ```
  *(Always use asynchronous / non-blocking execution so the shell is not blocked).*

## 3. Automated / E2E Testing (AltirraBridge)
- For programmatic verification, headless tests, or capturing screenshots:
  - Launch AltirraSDL with `--bridge`:
    ```powershell
    Start-Process -FilePath "C:\Users\grzes\Documents\Projects\AltirraSDL\build\windows-sdl-release\src\AltirraSDL\Release\AltirraSDL.exe" -ArgumentList "--bridge"
    ```
  - Read token file from `$env:LOCALAPPDATA\Temp\altirra-bridge-*.token`.
  - Use Python SDK (`from altirra_bridge import AltirraBridge`):
    - Boot binary: `atari.boot(str(Path("funky_koval.xex").resolve()))`
    - Advance deterministic frames: `atari.frame(120)`
    - Check registers or RAM: `atari.regs()`, `atari.peek(addr, length)`
    - Capture framebuffer: `atari.screenshot()`
    - Inject joystick/key actions: `atari.joy(0, "right", fire=True)`, `atari.key("SPACE")`

### AltirraBridge Safety & Pitfalls
- **Absolute Paths Only:** Always pass a resolved absolute path to `atari.boot(...)` (e.g. `str(Path("funky_koval.xex").resolve())`); relative paths can hang `AltirraSDL` indefinitely.
- **Stale Token Files (Windows PID Reuse):** Wait until `token_path.stat().st_mtime >= launch_time` with an explicit timeout deadline before connecting; never poll indefinitely.
- **Process Cleanup:** Always wrap `AltirraSDL --bridge` subprocesses in `try / finally` (`proc.terminate()` / `kill()`) so failed or timed-out scripts never leak CPU-burning background processes.
- **GTIA Read vs. Write Registers:** Do not use `peek($D000)` / `peek($D012)` to inspect `HPOSP0` / `COLPM0` (those addresses read `M0PF` / `TRIG2`). Use `atari.pmg()` (note values may be hex strings like `"$0e"` or `int`) or OS shadows (`PCOLR0`, `GPRIOR`, `SDMCTL`).
- **Exact Single-Frame Stepping:** On GUI `AltirraSDL.exe`, `frame(1)` can advance multiple frames; use a CPU breakpoint (`bp_set`) + `cycles(...)` (or headless `AltirraBridgeServer`) when exact single-frame RAM/PMG inspection is needed.

