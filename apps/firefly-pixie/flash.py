#!/usr/bin/env python3
"""
Firefly Pixie auto-flash script.

Usage:
  python3 flash.py            # build + flash once
  python3 flash.py --watch    # watch source for changes, rebuild + flash automatically

Requires:
  - Docker running (espressif/idf:v5.5.4 image)
  - esptool installed (pip install esptool)
  - Device on /dev/cu.usbmodem* or set FIREFLY_DEVICE_PATH env var
"""

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
BUILD_DIR    = SCRIPT_DIR / "build"
SRC_DIRS     = [SCRIPT_DIR / "main", SCRIPT_DIR / "components"]
IDF_IMAGE    = "espressif/idf:v5.5.4"
CHIP         = "esp32c3"
BAUD         = 460800
WATCH_EXTS   = {".c", ".h", ".cpp", ".cmake", "CMakeLists.txt"}
POLL_INTERVAL = 2  # seconds between change checks

BINARIES = [
    (0x0,     BUILD_DIR / "bootloader" / "bootloader.bin"),
    (0x8000,  BUILD_DIR / "partition_table" / "partition-table.bin"),
    (0x10000, BUILD_DIR / "firefly-pixie-treasury.bin"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str, color: str = "") -> None:
    codes = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m", "": ""}
    reset = "\033[0m" if color else ""
    print(f"{codes[color]}[flash] {msg}{reset}", flush=True)


def find_device() -> str | None:
    """Auto-detect the Firefly device port."""
    override = os.environ.get("FIREFLY_DEVICE_PATH")
    if override:
        return override
    import glob
    candidates = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    return candidates[0] if candidates else None


def source_fingerprint() -> str:
    """Hash all watched source files to detect changes."""
    h = hashlib.sha256()
    for src_dir in SRC_DIRS:
        if not src_dir.exists():
            continue
        for path in sorted(src_dir.rglob("*")):
            if path.is_file() and (path.suffix in WATCH_EXTS or path.name in WATCH_EXTS):
                h.update(str(path).encode())
                h.update(path.read_bytes())
    return h.hexdigest()


def build() -> bool:
    """Run idf.py build inside the ESP-IDF Docker container."""
    log("Building firmware with ESP-IDF v5.5.4 (Docker)…", "cyan")

    # Remove sdkconfig so defaults are always applied cleanly
    sdkconfig = SCRIPT_DIR / "sdkconfig"
    if sdkconfig.exists():
        sdkconfig.unlink()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/project",
        "-w", "/project",
        IDF_IMAGE,
        "bash", "-c",
        f"idf.py set-target {CHIP} 2>&1 && idf.py build 2>&1",
    ]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        log("Build FAILED.", "red")
        return False
    log("Build complete.", "green")
    return True


def flash(port: str) -> bool:
    """Flash all three binaries with esptool."""
    log(f"Flashing to {port} at {BAUD} baud…", "cyan")

    for _, path in BINARIES:
        if not path.exists():
            log(f"Missing binary: {path}", "red")
            return False

    args = [
        sys.executable, "-m", "esptool",
        "--chip", CHIP,
        "--port", port,
        "--baud", str(BAUD),
        "write-flash",
    ]
    for addr, path in BINARIES:
        args += [hex(addr), str(path)]

    result = subprocess.run(args, capture_output=False)
    if result.returncode != 0:
        log("Flash FAILED.", "red")
        return False
    log("Flash complete. Device is rebooting.", "green")
    return True


def build_and_flash() -> bool:
    port = find_device()
    if not port:
        log("No Firefly device found. Plug in USB and retry.", "red")
        return False
    log(f"Device found: {port}", "green")

    if not build():
        return False
    return flash(port)


# ── Watch mode ────────────────────────────────────────────────────────────────

def watch() -> None:
    log("Watch mode active. Monitoring source files for changes…", "yellow")
    log(f"Watching: {', '.join(str(d) for d in SRC_DIRS)}", "yellow")

    last_fp = source_fingerprint()
    log(f"Initial fingerprint: {last_fp[:12]}…", "yellow")

    # Do an initial build+flash on startup
    build_and_flash()

    while True:
        time.sleep(POLL_INTERVAL)
        fp = source_fingerprint()
        if fp != last_fp:
            log(f"Source changed ({fp[:12]}…). Rebuilding…", "yellow")
            last_fp = fp
            build_and_flash()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Firefly Pixie auto-flash")
    parser.add_argument("--watch", action="store_true",
                        help="Watch source files and auto-flash on changes")
    parser.add_argument("--flash-only", action="store_true",
                        help="Skip build, flash existing binaries")
    args = parser.parse_args()

    if args.flash_only:
        port = find_device()
        if not port:
            log("No device found.", "red")
            sys.exit(1)
        log(f"Device: {port}", "green")
        sys.exit(0 if flash(port) else 1)

    if args.watch:
        try:
            watch()
        except KeyboardInterrupt:
            log("Watch mode stopped.", "yellow")
    else:
        sys.exit(0 if build_and_flash() else 1)


if __name__ == "__main__":
    main()
