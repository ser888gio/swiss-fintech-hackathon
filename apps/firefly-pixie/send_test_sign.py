"""Send one sign request straight to the Pixie over COM5 and print the match code
it should display. Lets you verify the request path + Screen 2 + match code without
the bridge. Leaves the device on Screen 2 (60s) so you can do the button test.

Run with the IDF python env (bundles pyserial).
"""

import hashlib
import json
import sys
import time

import serial

PORT = "COM5"

DISPLAY = {
    "paymentId": "test-001",
    "amount": 125000.50,
    "currency": "USD",
    "dest": "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
    "network": "XRPL Testnet",
    "owner": "rOwnerAddr123456789abcdef",
    "escrowSequence": 42,
    "escrowCreateTxHash": "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
    "reference": "Invoice 2026-Q2",
}


def expected_match_code() -> str:
    canonical = "|".join(
        [
            "XRPL_TREASURY_APPROVAL_V1",
            DISPLAY["network"],
            DISPLAY["paymentId"],
            DISPLAY["owner"],
            DISPLAY["dest"],
            DISPLAY["currency"],
            f"{DISPLAY['amount']:.2f}",
            str(DISPLAY["escrowSequence"]),
            DISPLAY["escrowCreateTxHash"],
        ]
    )
    digest = hashlib.sha256(canonical.encode()).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 10000:04d}"


def log(msg: str) -> None:
    sys.stderr.write(f"[test] {msg}\n")
    sys.stderr.flush()


def main() -> int:
    code = expected_match_code()
    log(
        f"EXPECTED on device -> amount {DISPLAY['amount']:.2f} {DISPLAY['currency']}, MATCH CODE {code[0]} {code[1]} {code[2]} {code[3]}"
    )

    msg = (
        json.dumps({"cmd": "sign", "display": DISPLAY}, separators=(",", ":")) + "\n"
    ).encode()

    port = serial.Serial(PORT, 115200, timeout=0.2)
    time.sleep(2.5)  # if opening the port reset the chip, let it boot back to standby
    for attempt in range(3):
        try:
            port.reset_input_buffer()
            port.write(msg)
            port.flush()
            break
        except Exception as exc:  # noqa: BLE001
            log(f"write retry ({exc})")
            try:
                port.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
            port = serial.Serial(PORT, 115200, timeout=0.2)
    log(
        "sign request sent; reading 5s (silence = device is on Screen 2, waiting for a button)"
    )

    start = time.time()
    got = b""
    while time.time() - start < 5:
        data = port.read(4096)
        if data:
            got += data
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
    port.close()
    if not got.strip():
        log(
            "no reply yet — Screen 2 is up. Press SW2 (refresh) / SW4 (approve) / SW1 (reject)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
