# Flashing the Firefly Pixie Treasury Firmware

This document describes how we built and flashed the custom treasury firmware
onto a **Firefly Pixie** hardware device, captured its public key, and got the
on-device approval screen working. Follow it to reproduce the setup on another
machine or device.

---

## 1. Goal

We want the Firefly Pixie to act as the **physical veto** in the treasury flow:

1. The local `firefly-bridge` sends a payment's details to the device over USB.
2. The device **displays** the payment (network, amount, recipient, escrow info).
3. The operator physically presses **APPROVE** or **REJECT** on the device.
4. On APPROVE, the device **signs** a canonical approval payload with its own
   on-device secp256k1 private key and returns the signature.
5. The backend verifies that signature against the device's **public key**.

For any of this to work, the device must run *our* firmware (`apps/firefly-pixie`)
— not the stock Firefly firmware it ships with. This session was about getting
that firmware to **build, flash, boot, and drive the screen**, plus extracting
the device's public key so the bridge/backend can verify signatures.

> **Security boundary (unchanged):** the device decides nothing about policy. It
> only displays what it's told, waits for a human button press, and signs a
> fixed payload. The signing key never leaves the device.

---

## 2. Hardware

- **Device:** Firefly Pixie, ESP32-C3 (RISC-V), chip revision v0.4.
- **Connection:** USB cable from the PC to the device. It enumerates as a
  **USB-Serial/JTAG** port — on this machine it came up as **COM5**.
- The device's only USB endpoint is the USB-Serial-JTAG bridge; the firmware
  uses it for both the console logs and the bridge's request/response protocol.

---

## 3. Toolchain / dependencies installed

The firmware is an **ESP-IDF** project (Espressif's SDK for ESP32 chips). It is
**not** an npm/Node project — it builds with `idf.py`, not `npm`.

| Dependency | Version we used | Notes |
|------------|-----------------|-------|
| **ESP-IDF** | **v5.5.4** | Installed via the Espressif Windows installer to `C:\Espressif`. |
| RISC-V toolchain | gcc 14.2.0 (`riscv32-esp-elf`) | Installed automatically by the IDF installer. |
| Python (IDF env) | 3.11.2 | Bundled in the IDF Python venv at `C:\Espressif\python_env\idf5.5_py3.11_env`. |
| CMake + Ninja | bundled with IDF | Provided by the IDF environment, not the system. |

### Why ESP-IDF v5.4+ (and why we landed on 5.5.4)

The firmware depends on the `esp_security` component, which provides the Digital
Signature (`esp_ds`) peripheral headers. **`esp_security` only exists in
ESP-IDF v5.4 and newer.** On older v5.3.x it was located inside `esp_hw_support`,
which caused build failures. We installed **v5.5.4** and it cleared every
framework-level error.

### Activating the environment (every new terminal)

ESP-IDF needs its environment activated before `idf.py` works (otherwise you get
`"cmake" must be available on the PATH` and `IDF_PYTHON_ENV_PATH is missing`).

The easiest path on Windows is the Start Menu shortcut installed by the
installer:

> **ESP-IDF 5.5 CMD** (or **ESP-IDF 5.5 PowerShell**)

Opening that shortcut runs the activation and prints:

```
Activating ESP-IDF 5.5
...
Done! You can now compile ESP-IDF projects.
```

All `idf.py` commands below must be run from a terminal that has been activated
this way, in the project directory:

```
C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-pixie
```

---

## 4. Build configuration we had to add

The upstream firmware shipped **no `sdkconfig.defaults`**, but the code requires
several features to be enabled. Without them the build fails (missing NimBLE
headers, undefined FreeRTOS symbols, etc.). We created
`apps/firefly-pixie/sdkconfig.defaults` with:

```ini
# BLE (NimBLE) — task-ble.c includes nimble/nimble_port.h unconditionally.
CONFIG_BT_ENABLED=y
CONFIG_BT_NIMBLE_ENABLED=y

# FreeRTOS task tags — panel.c / hollows.c / task-io.c use
# vTaskSetApplicationTaskTag / xTaskGetApplicationTaskTag.
CONFIG_FREERTOS_USE_APPLICATION_TASK_TAG=y

# Trace facility — panel.c / task-ble.c call vTaskGetInfo(), which is
# gated behind configUSE_TRACE_FACILITY.
CONFIG_FREERTOS_USE_TRACE_FACILITY=y

# Console over USB-Serial-JTAG (the device's only USB endpoint).
CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y

# Larger app partition: a BLE app does not fit the default factory size.
CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE=y
```

> **Important:** `sdkconfig.defaults` is only applied when the generated
> `sdkconfig` doesn't yet exist. If you change `sdkconfig.defaults` after a build,
> delete the generated `sdkconfig` so the new defaults take effect:
> ```
> del sdkconfig
> idf.py build
> ```

---

## 5. Source fixes we made

These are the code changes required to get a clean build and a booting device.

### 5.1 `main/main.c` — reply buffer too small (compile error)

The JSON sign-reply buffer could overflow (`-Werror=format-truncation`). The
signature is 130 hex chars, so the reply can be up to 161 bytes.

- `char reply[160];` → **`char reply[200];`**

### 5.2 `main/panel_approve.c` — duplicate macro (warning)

`COLOR_APPROVE` is already defined in `firefly-hollows.h` (as `COLOR_GREEN`). We
removed the local redefinition and kept only `COLOR_REJECT`.

### 5.3 `components/firefly-hollows/src/device-info.c` — display crash fix (the big one)

**Symptom:** the firmware booted, printed the public key, then **panicked**:

```
E (195) spi: spi_bus_initialize(816): SPI bus already initialized.
assert failed: ffx_display_init display.c:352 (result == ESP_OK)
```

**Root cause:** this Pixie unit has its **eFuse model/serial burned**
(`serial=971`) but it has **no `attest` secure-NVS partition** (our partition
table is `nvs / phy_init / factory` only — the stock firmware's secure
attestation data is not present). The upstream `ffx_deviceInit()` bails out with
`MissingNvs` (status 41) *before* it stores the model number, and the hardware
config lookup was gated behind `if (status)`. The result: `ffx_deviceInfo()`
returned a **zeroed** display config (`displayBus = 0`), and host 0 is the
**flash SPI bus**, which is already initialized → the assert killed the boot.

The display/keypad wiring is determined purely by the **eFuse model number** and
has nothing to do with secure attestation, so we decoupled the two:

1. Store the eFuse `modelNumber` / `serialNumber` **before** the secure-NVS
   checks, so a unit without an `attest` partition still reports a usable
   hardware config.
2. In `ffx_deviceModelInfo()`, decode the wiring whenever the model number is
   valid (`if (modelNumber <= 0) return;`) instead of requiring full secure
   provisioning (`if (status) return;`).

We **do not** use Firefly's attestation/`esp_ds` features — the firmware signs
with its own secp256k1 key stored in the `treasury` NVS namespace — so dropping
the attestation requirement is safe for our use case. The
`Missing nvs.attest` warnings still print on boot and are expected/harmless.

---

## 6. Build & flash procedure (the steps you actually run)

From an **activated ESP-IDF 5.5 terminal**, in `apps/firefly-pixie`:

```bash
# 1. Select the chip (first time, or after deleting build/)
idf.py set-target esp32c3

# 2. Build
idf.py build
#    → ends with "Project build complete" when successful

# 3. Flash + open serial monitor (device on COM5)
idf.py -p COM5 flash monitor
#    → Ctrl+] to exit the monitor
```

**Free the COM port first.** If the `firefly-bridge` or a browser tab using Web
Serial is holding COM5, the flash fails with "access denied". Close them before
flashing.

### What a good boot looks like

```
[treasury] FIREFLY_PUBLIC_KEY=dbfe499a8887919a267320a7544000e1cc962fd433073211a5bb319f330af7c2324e4fd72bb08fce5daea9e78e52064bf52714074abe718cfcb48e98ada5ce01
Corrupt: Missing nvs.attest.secure (serial=971, ...)   <-- expected, harmless
[main.1:ffx_init:99] device: status=41 (unprovisioned)  <-- expected, harmless
```

…and then the **screen lights up** and shows the waiting panel (no
`ffx_display_init` assert).

---

## 7. The device public key

On first boot the firmware generates a secp256k1 key, stores it in NVS, and
prints the **64-byte uncompressed public key** (without the `0x04` prefix):

```
FIREFLY_PUBLIC_KEY=dbfe499a8887919a267320a7544000e1cc962fd433073211a5bb319f330af7c2324e4fd72bb08fce5daea9e78e52064bf52714074abe718cfcb48e98ada5ce01
```

This value:

- is **stable** across reboots (stored in NVS),
- must be given to the `firefly-bridge` / backend as `FIREFLY_PUBLIC_KEY` so the
  signatures the device returns can be verified.

> Treat the public key as configuration, not a secret. The **private** key never
> leaves the device.

---

## 8. The canonical approval payload (must stay in sync)

When the operator approves, the device signs the SHA-256 of this exact string:

```
XRPL_TREASURY_APPROVAL_V1|{network}|{paymentId}|{owner}|{dest}|{currency}|{amount:.2f}|{escrowSequence}|{escrowCreateTxHash}
```

This format **must remain byte-for-byte identical** in all three places:

- `apps/firefly-pixie/main/main.c` → `compute_digest()`
- `apps/firefly-bridge/src/device.ts` → `deriveDigest()`
- `apps/api/app/tools/firefly.py` → `canonical_payload()`

If you change one, change all three, or signature verification will fail.

---

## 9. End-to-end test (display + confirm)

1. Flash the firmware and confirm the screen comes up (Section 6).
2. Set `FIREFLY_PUBLIC_KEY` (Section 7) and `FIREFLY_DEVICE_PATH=COM5` for the
   bridge, then start the bridge (`npm run dev:bridge`, port 4747, local only).
3. Run the test script:
   ```
   apps/firefly-bridge/test-sign.ps1
   ```
   It POSTs a sample payment to `localhost:4747/sign`.
4. The payment details appear on the device screen. Press **APPROVE** within the
   30-second window.
5. The bridge receives `{"status":"ok","signature":"..."}`.

---

## 10. Troubleshooting quick reference

| Symptom | Cause | Fix |
|---------|-------|-----|
| `"cmake" must be available on the PATH` | IDF environment not activated | Open the **ESP-IDF 5.5 CMD** shortcut; run `idf.py` from there. |
| `esp_ds.h` / `esp_security` not found | ESP-IDF older than v5.4 | Install ESP-IDF **v5.4+** (we used v5.5.4). |
| `nimble/nimble_port.h: No such file` | NimBLE not enabled | Ensure `sdkconfig.defaults` has the BLE options; `del sdkconfig` and rebuild. |
| `undefined reference to vTaskGetInfo` | trace facility off | `CONFIG_FREERTOS_USE_TRACE_FACILITY=y`; `del sdkconfig` and rebuild. |
| `snprintf output may be truncated` | reply buffer too small | `reply[200]` in `main.c`. |
| `spi_bus_initialize: already initialized` + display assert | zeroed display config on a unit without `attest` NVS | The `device-info.c` fixes in Section 5.3. |
| Flash "access denied" | COM port held by bridge/browser | Close the bridge and any Web Serial browser tabs. |
| Changed `sdkconfig.defaults`, no effect | defaults only apply when no `sdkconfig` | `del sdkconfig`, then `idf.py build`. |
