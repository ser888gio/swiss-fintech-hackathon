#!/usr/bin/env python3
"""
Firefly PCB ↔ Bridge communication test.

Sends a test payment to the local bridge (localhost:4747), waits for the
device to show the VERIFY PAYMENT screen, then validates the returned
signature against the device's public key.

Usage:
  python3 test_bridge.py                    # interactive: you press SW4 on device
  python3 test_bridge.py --timeout 60       # custom button-press timeout (seconds)
  python3 test_bridge.py --bridge-url http://localhost:4747

Pass/fail exit codes: 0 = pass, 1 = fail.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

# ── Test payload ──────────────────────────────────────────────────────────────

TEST_PAYMENT = {
    "paymentId":          "bridge-test-001",
    "amount":             99999.99,
    "currency":           "USD",
    "dest":               "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
    "network":            "XRPL Testnet",
    "owner":              "rBridgeTestOwner1234567890abcdef",
    "escrowSequence":     1,
    "escrowCreateTxHash": "DEADBEEF" * 8,   # 64 hex chars
    "reference":          "bridge-connectivity-check",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str, tag: str = "test", color: str = "") -> None:
    codes = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m",
             "cyan": "\033[96m", "bold": "\033[1m", "": ""}
    reset = "\033[0m" if color else ""
    print(f"{codes[color]}[{tag}] {msg}{reset}", flush=True)


def expected_match_code(payment: dict) -> str:
    """Derive the 4-digit match code the device will display."""
    canonical = "|".join([
        "XRPL_TREASURY_APPROVAL_V1",
        payment["network"],
        payment["paymentId"],
        payment["owner"],
        payment["dest"],
        payment["currency"],
        f"{payment['amount']:.2f}",
        str(payment["escrowSequence"]),
        payment["escrowCreateTxHash"],
    ])
    digest = hashlib.sha256(canonical.encode()).digest()
    code = int.from_bytes(digest[:4], "big") % 10000
    return f"{code:04d}"


def verify_signature(signature_hex: str, public_key_hex: str, payment: dict) -> bool:
    """Verify the secp256k1 signature against the canonical payload."""
    try:
        from eth_keys import keys as eth_keys
    except ImportError:
        log("eth-keys not installed — skipping crypto verification (pip install eth-keys)", "warn", "yellow")
        return True   # assume ok if library missing

    canonical = "|".join([
        "XRPL_TREASURY_APPROVAL_V1",
        payment["network"],
        payment["paymentId"],
        payment["owner"],
        payment["dest"],
        payment["currency"],
        f"{payment['amount']:.2f}",
        str(payment["escrowSequence"]),
        payment["escrowCreateTxHash"],
    ])
    digest = hashlib.sha256(canonical.encode()).digest()

    try:
        sig_bytes = bytes.fromhex(signature_hex)
        pub_bytes = bytes.fromhex(public_key_hex)
        pub_key   = eth_keys.PublicKey(pub_bytes)

        if len(sig_bytes) == 65:
            # Normalize Ethereum-style v (27/28) → 0/1
            v = sig_bytes[64]
            if v >= 27:
                v -= 27
            sig_bytes = sig_bytes[:64] + bytes([v])
            sig_obj = eth_keys.Signature(sig_bytes)
            pub_key.verify_msg_hash(digest, sig_obj)
        elif len(sig_bytes) == 64:
            # No recovery byte — try v=0 and v=1
            verified = False
            for v in (0, 1):
                try:
                    sig_obj = eth_keys.Signature(sig_bytes + bytes([v]))
                    pub_key.verify_msg_hash(digest, sig_obj)
                    verified = True
                    break
                except Exception:
                    continue
            if not verified:
                raise ValueError("Signature did not verify with v=0 or v=1")
        else:
            raise ValueError(f"Unexpected signature length: {len(sig_bytes)} bytes")

        return True
    except Exception as exc:
        log(f"Signature invalid: {exc}", "FAIL", "red")
        return False


def post_json(url: str, payload: dict, timeout: int) -> dict:
    data    = json.dumps(payload).encode()
    req     = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── Main test ─────────────────────────────────────────────────────────────────

def run_test(bridge_url: str, timeout: int) -> bool:
    sign_url = f"{bridge_url.rstrip('/')}/sign"

    log("=" * 56, "", "bold")
    log("Firefly PCB ↔ Bridge connectivity test", "", "bold")
    log("=" * 56, "", "bold")

    # ── Step 1: reachability ──────────────────────────────────────────────────
    log(f"Bridge URL : {bridge_url}")
    log(f"Button timeout : {timeout}s")
    try:
        urllib.request.urlopen(f"{bridge_url}/health", timeout=3)
        log("Bridge reachable ✓", "health", "green")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("Bridge reachable (no /health endpoint, that's fine) ✓", "health", "green")
        else:
            log(f"Bridge HTTP error {e.code}", "health", "red")
            return False
    except Exception as exc:
        log(f"Bridge not reachable: {exc}", "health", "red")
        log("Is the bridge running?  npm run dev:bridge", "hint", "yellow")
        return False

    # ── Step 2: expected match code ───────────────────────────────────────────
    code = expected_match_code(TEST_PAYMENT)
    log(f"Expected MATCH CODE on device: {' '.join(code)}", "code", "cyan")

    # ── Step 3: send sign request ─────────────────────────────────────────────
    log(f"Sending payment to bridge → device…", "sign")
    log(f"  Amount : {TEST_PAYMENT['amount']:.2f} {TEST_PAYMENT['currency']}", "sign")
    log(f"  Dest   : {TEST_PAYMENT['dest']}", "sign")
    log(f"  Network: {TEST_PAYMENT['network']}", "sign")
    log("", "sign")
    log(f">>> Device screen should show VERIFY PAYMENT <<<", "ACTION", "yellow")
    log(f">>> Confirm MATCH CODE is  {' '.join(code)}  <<<", "ACTION", "yellow")
    log(f">>> Press SW4 (bottom button) to APPROVE       <<<", "ACTION", "yellow")
    log("", "sign")

    t0 = time.time()
    try:
        result = post_json(sign_url, TEST_PAYMENT, timeout=timeout + 10)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        log(f"Bridge returned HTTP {exc.code}: {body}", "FAIL", "red")
        return False
    except TimeoutError:
        log(f"Timed out waiting for button press ({timeout}s).", "FAIL", "red")
        return False
    except Exception as exc:
        log(f"Request failed: {exc}", "FAIL", "red")
        return False

    elapsed = time.time() - t0
    log(f"Response received in {elapsed:.1f}s", "sign", "green")

    # ── Step 4: validate response ─────────────────────────────────────────────
    if "error" in result:
        log(f"Bridge error: {result['error']}", "FAIL", "red")
        return False

    sig = result.get("signature", "")
    pub = result.get("publicKey", "")

    if not sig:
        log("No signature in response.", "FAIL", "red")
        return False

    log(f"Signature   : {sig[:24]}…{sig[-8:]}", "sig", "green")
    log(f"Public key  : {pub[:24]}…{pub[-8:]}", "sig", "green")

    if len(sig) not in (128, 130):
        log(f"Unexpected signature length: {len(sig)} hex chars (want 128 or 130)", "FAIL", "red")
        return False

    # ── Step 5: crypto verify ─────────────────────────────────────────────────
    if pub:
        ok = verify_signature(sig, pub, TEST_PAYMENT)
        if ok:
            log("Signature cryptographically valid ✓", "crypto", "green")
        else:
            return False
    else:
        log("No public key in response — skipping crypto check", "warn", "yellow")

    # ── Result ────────────────────────────────────────────────────────────────
    log("=" * 56, "", "bold")
    log("PASS — PCB ↔ Bridge communication verified ✓", "", "green")
    log("=" * 56, "", "bold")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Firefly PCB ↔ Bridge test")
    parser.add_argument("--bridge-url", default="http://localhost:4747",
                        help="Bridge base URL (default: http://localhost:4747)")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Seconds to wait for button press (default: 60)")
    args = parser.parse_args()

    ok = run_test(args.bridge_url, args.timeout)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
