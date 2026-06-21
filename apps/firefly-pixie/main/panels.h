#pragma once

#include <stddef.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "firefly-color.h"

// ── Payment request the device displays and signs ──────────────────────────────
//
// Filled by parse_sign_request() in main.c from the bridge's {"cmd":"sign", ...}
// message, copied into each panel's own state so it outlives the serial buffer.

typedef struct {
    char payment_id[64];
    char network[32];
    char owner[128];
    char dest[128];
    char currency[16];
    double amount;
    uint32_t escrow_sequence;
    char escrow_create_tx_hash[128];
    char reference[128];
    uint16_t match_code;   // precomputed by the serial task; see treasury_match_code
} ApproveRequest;

// serial task → standby panel: a new payment to display (depth-1 queue).
extern QueueHandle_t g_request_queue;

// transaction panel → serial task: 1 (approved) or 0 (rejected/expired).
extern QueueHandle_t g_approval_queue;

// ── Outcome of the on-device decision ───────────────────────────────────────────
//
// The integer pushed onto g_approval_queue is `outcome == TreasuryOutcomeApproved`
// (1 to sign, 0 otherwise); the richer enum drives the result screen's copy.

typedef enum TreasuryOutcome {
    TreasuryOutcomeRejected = 0,
    TreasuryOutcomeApproved = 1,
    TreasuryOutcomeExpired  = 2,
} TreasuryOutcome;

// ── Palette (mirrors the web dashboard :root tokens) ────────────────────────────
//
// ffx_color_rgb() builds a color_ffxt at call time, so these are macros, not
// constants. APPROVE/REJECT keep a green/red affordance for safety even though
// the web palette collapses both into orange — colour is the last line of defence
// on a veto device.

#define COLOR_PAPER          (ffx_color_rgb(0xeb, 0xea, 0xe9))  // --paper  : primary text
#define COLOR_STONE          (ffx_color_rgb(0x95, 0x91, 0x90))  // --stone  : muted labels
#define COLOR_ORANGE         (ffx_color_rgb(0xd1, 0x67, 0x1f))  // --orange : accent
#define COLOR_ORANGE_BRIGHT  (ffx_color_rgb(0xef, 0x7c, 0x24))  // --accent-strong
#define COLOR_BROWN          (ffx_color_rgb(0x48, 0x3c, 0x35))  // --brown  : frame
#define COLOR_GO             (ffx_color_rgb(0x4a, 0xc7, 0x7d))  // approve (safety green)
#define COLOR_STOP           (ffx_color_rgb(0xcc, 0x33, 0x22))  // reject  (safety red)

// ── Canonical payload + match code (kept in sync with bridge + backend) ─────────
//
// treasury_match_code() derives a deterministic 4-digit code from the SHA-256 of
// the canonical approval payload. The bridge (device.ts) and backend (firefly.py)
// compute the identical value, so the operator can visually confirm the device is
// displaying the exact transaction the dashboard sent. It is display-only: the
// secp256k1 signature over the same payload remains the release mechanism.
//
// treasury_match_code uses a 1KB stack buffer — call it from the serial task, not
// from a Hollows panel task (those have only ~4KB of stack).

size_t treasury_canonical_payload(const ApproveRequest *req, char *out, size_t out_len);
uint16_t treasury_match_code(const ApproveRequest *req);  // 0..9999

// ── Screens ─────────────────────────────────────────────────────────────────────

// Screen 1: standby. Root panel; polls g_request_queue and pushes the transaction
// screen when a payment arrives. Never pops.
int pushPanelStandby(void);

// Screen 2: the transaction + 4-digit match code. SW2 re-rolls the code, SW4
// approves, SW1 rejects. Blocks (its own task) until the operator decides or it
// times out, then returns the TreasuryOutcome.
int pushPanelTransaction(const ApproveRequest *req);

// Screen 3: result. Shows APPROVED / REJECTED / EXPIRED, then auto-dismisses.
int pushPanelResult(TreasuryOutcome outcome);
