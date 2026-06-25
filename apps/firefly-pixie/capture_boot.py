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
    # Phase 1 — pulse EN (RTS) low→high to reset the chip into the app.
    try:
        p = open_port()
        p.setDTR(False)  # IO9 high → normal boot (not download)
        p.setRTS(True)  # EN low  → hold in reset
        time.sleep(0.15)
        p.setRTS(False)  # EN high → release, boot
        log("reset pulse sent")
    except Exception as exc:  # noqa: BLE001
        log(f"reset open failed: {exc}")
        p = None

    # Phase 2 — read, reopening across the USB re-enumeration.
    start = time.time()
    total = 0
    while time.time() - start < READ_SECONDS:
        if p is None:
            try:
                p = open_port()
                log("reopened port")
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
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

    log(f"captured {total} bytes")
    try:
        p.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
