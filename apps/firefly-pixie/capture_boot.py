"""Reset the Firefly Pixie (ESP32-C3, USB-Serial/JTAG) and capture its boot log.

idf_monitor needs an interactive TTY, which a background shell lacks. The C3's
USB-Serial/JTAG re-enumerates when the chip resets (the COM port drops and comes
back), so this resets via the EN line, then reconnects across the re-enumeration
and reads for a fixed window. pyserial ships with the IDF python env.
"""

import sys
import time

import serial

PORT = "COM5"
READ_SECONDS = 15


def log(msg: str) -> None:
    sys.stderr.write(f"[capture] {msg}\n")
    sys.stderr.flush()


def open_port():
    return serial.Serial(PORT, 115200, timeout=0.1)


def main() -> int:
    p = reset_device()
    total = read_boot_log(p)
    log(f"captured {total} bytes")
    return 0


def reset_device():
    # Pulse EN (RTS) low/high to reset the chip into the app.
    try:
        p = open_port()
        p.setDTR(False)  # IO9 high means normal boot, not download mode.
        p.setRTS(True)  # EN low holds reset.
        time.sleep(0.15)
        p.setRTS(False)  # EN high releases reset.
        log("reset pulse sent")
        return p
    except Exception as exc:  # noqa: BLE001
        log(f"reset open failed: {exc}")
        return None


def read_boot_log(p) -> int:
    # Read, reopening across the USB re-enumeration.
    start = time.time()
    total = 0
    while time.time() - start < READ_SECONDS:
        p = ensure_open(p)
        if p is None:
            continue
        try:
            data = p.read(4096)
        except Exception as exc:  # noqa: BLE001
            log(f"read error ({exc}); reopening")
            try:
                p.close()
            except Exception:  # noqa: BLE001
                pass
            p = None
            time.sleep(0.2)
            continue
        if data:
            total += len(data)
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
    close_port(p)
    return total


def ensure_open(p):
    if p is not None:
        return p
    try:
        p = open_port()
        log("reopened port")
        return p
    except Exception:  # noqa: BLE001
        time.sleep(0.2)
        return None


def close_port(p) -> None:
    if p is None:
        return
    try:
        p.close()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
