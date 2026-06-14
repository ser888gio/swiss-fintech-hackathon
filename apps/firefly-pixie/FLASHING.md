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

### 5.4 `main/main.c` — uncleared background (tiled/garbled screen)

**Symptom:** the screen drove pixels but showed **tiled garbage** — the same
content repeated ~5× down the display, with text barely legible on top.

**Root cause:** `app_main()` passed a no-op background function (`noBg`) to
`ffx_init()`. The display uses two reused fragment buffers for the ten 24-px
bands; if nothing repaints the background, each buffer keeps **stale pixels from
two fragments earlier** (240 ÷ 48 = 5 repeats). The framework only installs its
own full-screen `COLOR_BLACK` clear when the background function is **`NULL`** —
a non-NULL no-op suppresses that.

**Fix:** pass `NULL` instead of `noBg`:

```c
ffx_init(FFX_VERSION(0, 0, 1), NULL, initPanel, NULL);
```

### 5.5 `components/firefly-hollows/src/task-io.c` — screen rotation

**Symptom:** after the background fix the screen was clean but rendered **rotated
90°** (text running sideways, long values clipped off the edge).

**Root cause:** `ffx_display_init()` was called with
`FfxDisplayRotationRibbonBottom`. This unit mounts the button board / display
ribbon on the **right**, so it needs the rotated mode.

**Fix:** use `FfxDisplayRotationRibbonRight`:

```c
display = ffx_display_init(device.displayBus, device.displayDCPin,
  device.displayResetPin, FfxDisplayRotationRibbonRight, renderScene, NULL);
```

> The firmware only implements two rotations (`RibbonBottom`, `RibbonRight`). If
> a future unit needs a different orientation, the MADCTL operand and the 240×240
> GRAM offset must be added in `components/firefly-display/src/display.c`.

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

This needs **two** PowerShell windows: one runs the bridge (and holds COM5 open),
the other fires a test payment at it.

> **COM5 is exclusive.** Only one thing can own the port at a time. To **flash**,
> the bridge and `idf.py monitor` must be closed. To **run the bridge**, no
> `idf.py monitor` may be running. Symptom of a conflict: the bridge fails to
> open COM5, or flashing reports "access denied".

### 9.1 Window A — start the bridge (leave it running)

The bridge script is `dev` (run from inside the bridge package). The root-level
alias `dev:bridge` only exists when you run it from the repo root — **inside
`apps/firefly-bridge` the script is just `dev`.**

```powershell
cd C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-bridge
$env:FIREFLY_DEVICE_PATH = "COM5"
$env:FIREFLY_PUBLIC_KEY  = "dbfe499a8887919a267320a7544000e1cc962fd433073211a5bb319f330af7c2324e4fd72bb08fce5daea9e78e52064bf52714074abe718cfcb48e98ada5ce01"
npm run dev
```

Wait for:

```
Firefly bridge listening on http://localhost:4747
```

The `$env:` vars apply only to the window they're set in, and they don't persist
between sessions. (Alternatively, put them in `.env`.) From the repo root the
equivalent is `npm run dev:bridge`, but you must still set the two vars in that
same window first.

### 9.2 Window B — send a test payment

```powershell
cd C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-bridge
./test-sign.ps1
```

It POSTs a sample payment to `localhost:4747/sign`. If you see
`Invoke-RestMethod : ... cannot connect to the remote server`, the bridge in
Window A isn't running (or isn't listening yet).

### 9.3 On the device

The screen switches from **"Waiting for approval…"** to the **Treasury Veto**
panel showing the full payment: Network, **Amount** (`125000.50 USD`), **To**
(recipient), Owner, Escrow seq, Escrow tx, Ref — then **APPROVE** / **REJECT**
buttons.

**Approving (button mapping).** The four buttons map by index → key as:
`{Cancel, OK, North(up), South(down)}`. In physical top-to-bottom order on this
unit (SW1→SW4):

| Button | Role |
| ------ | ---- |
| **SW1** (top) | Cancel |
| **SW2** | **OK / confirm** |
| **SW3** | Up |
| **SW4** (bottom) | Down |

When the panel opens **nothing is highlighted** (OK alone does nothing). So:

1. Press **SW4 (Down)** → highlights **APPROVE** (the first button).
2. Press **SW2 (OK)** → confirms.

(If the highlight moves the opposite way — silk-screen order can vary by unit —
use whichever of SW3/SW4 lands on APPROVE, then SW2.) You have **30 seconds**
before the firmware times out and replies `approval timeout`.

### 9.4 Expected result

Window B (`test-sign.ps1`) prints the bridge's reply:

```text
status     signature
------     ---------
ok         <130 hex chars>
```

- **APPROVE** → `{"status":"ok","signature":"..."}`
- **REJECT** → `{"status":"rejected"}`
- no press within 30 s → `{"status":"error","message":"approval timeout"}`

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
| Tiled/garbled screen (content repeated ~5×) | background never cleared | Pass `NULL` (not a no-op) for the background in `ffx_init` — Section 5.4. |
| Screen clean but rotated 90° / values clipped | wrong display rotation | Use `FfxDisplayRotationRibbonRight` in `task-io.c` — Section 5.5. |
| `npm error Missing script: "dev:bridge"` | wrong script inside the bridge package | Run `npm run dev` from `apps/firefly-bridge` (`dev:bridge` is the repo-root alias). |
| `Invoke-RestMethod: cannot connect to the remote server` | bridge not running | Start the bridge first (Section 9.1); leave it open before running the test. |
| Flash "access denied" | COM port held by bridge/browser/monitor | Close the bridge, `idf.py monitor`, and any Web Serial browser tabs. |
| Changed `sdkconfig.defaults`, no effect | defaults only apply when no `sdkconfig` | `del sdkconfig`, then `idf.py build`. |

---

## 11. Command quick reference

**Build & flash** (from an activated **ESP-IDF 5.5** terminal):

```bat
cd C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-pixie
idf.py build
idf.py -p COM5 flash monitor
```

**Run the bridge** (separate, non-IDF PowerShell window — see Section 9.1):

```powershell
cd C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-bridge
$env:FIREFLY_DEVICE_PATH = "COM5"
$env:FIREFLY_PUBLIC_KEY  = "dbfe499a8887919a267320a7544000e1cc962fd433073211a5bb319f330af7c2324e4fd72bb08fce5daea9e78e52064bf52714074abe718cfcb48e98ada5ce01"
npm run dev
```

**Send a test payment** (third window — see Section 9.2):

```powershell
cd C:\Users\nicas\Desktop\swiss-fintech-hackathon\apps\firefly-bridge
./test-sign.ps1
```
