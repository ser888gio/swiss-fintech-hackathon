#include <stdio.h>
#include <string.h>

#include "esp_random.h"

#include "firefly-hollows.h"
#include "firefly-scene.h"

#include "panels.h"

// Screen 2 — Transaction + 4-digit match code.
//
// Shows the payment the operator is about to release and a 4-digit MATCH CODE
// (precomputed by the serial task in req.match_code). The dashboard derives the
// same code, so matching the two proves the device is displaying the exact
// transaction the backend sent (a WYSIWYS / anti-tamper check). The code is
// display-only — releasing still requires the secp256k1 signature.
//
// Buttons (per FLASHING.md §9.3 mapping):
//   SW2 / Ok     → re-roll the code (a liveness "refresh"; it re-derives to the
//                  same value, so it always still matches the dashboard)
//   SW4 / South  → APPROVE  (queues 1; serial task signs)
//   SW1 / Cancel → REJECT   (queues 0)
// No decision within APPROVAL_TIMEOUT_MS auto-expires (queues 0).

#define APPROVAL_TIMEOUT_MS   (60000)
#define SCRAMBLE_MS             (700)   // duration of the refresh animation
#define SCRAMBLE_STEP_MS         (60)   // how often the scrambled digits change

#define CHIP_W   (150)
#define CHIP_H    (46)
#define CHIP_X   ((240 - CHIP_W) / 2)
#define CHIP_Y   (124)

typedef struct {
    ApproveRequest req;
    FfxNode codeLabel;
    uint16_t code;

    bool started;
    uint32_t startTicks;

    bool scrambleRequested;
    uint32_t scrambleUntil;
    uint32_t lastScramble;

    bool decided;
} TxState;

// Render the code as spaced digits, e.g. 4729 → "4 7 2 9".
static void setCodeText(FfxNode label, uint16_t v) {
    char d[5];
    snprintf(d, sizeof(d), "%04u", (unsigned)(v % 10000));
    char spaced[8] = { d[0], ' ', d[1], ' ', d[2], ' ', d[3], '\0' };
    ffx_sceneLabel_setText(label, spaced);
}

// "rPjk2Q9a..h7Hk" — keep the leading 'r' tag and trailing chars visible.
static void shortenAddress(const char *src, char *out, size_t outLen) {
    size_t n = strlen(src);
    if (n + 1 <= outLen && n <= 14) {
        snprintf(out, outLen, "%s", src);
        return;
    }
    snprintf(out, outLen, "%.8s..%s", src, src + n - 4);
}

static void decide(TxState *state, TreasuryOutcome outcome) {
    if (state->decided) { return; }
    state->decided = true;

    int approved = (outcome == TreasuryOutcomeApproved) ? 1 : 0;
    xQueueSend(g_approval_queue, &approved, 0);

    pushPanelResult(outcome);   // blocks until the result screen dismisses
    ffx_popPanel((int)outcome); // …then return to standby
}

static void onKeys(FfxEvent event, FfxEventProps props, void *arg) {
    TxState *state = arg;

    switch ((~props.keys.down) & props.keys.changed) {  // keys released this tick
        case FfxKeyOk:      // SW2 — refresh the code (handled on next render tick)
            state->scrambleRequested = true;
            break;
        case FfxKeySouth:   // SW4 — approve
            decide(state, TreasuryOutcomeApproved);
            break;
        case FfxKeyCancel:  // SW1 — reject
            decide(state, TreasuryOutcomeRejected);
            break;
    }
}

static void onRender(FfxEvent event, FfxEventProps props, void *arg) {
    TxState *state = arg;
    uint32_t now = props.render.ticks;

    if (!state->started) { state->started = true; state->startTicks = now; }

    if (state->scrambleRequested) {
        state->scrambleRequested = false;
        state->scrambleUntil = now + SCRAMBLE_MS;
        state->lastScramble = 0;
        ffx_sceneLabel_setTextColor(state->codeLabel, COLOR_ORANGE_BRIGHT);
    }

    if (state->scrambleUntil) {
        if (now >= state->scrambleUntil) {
            state->scrambleUntil = 0;
            setCodeText(state->codeLabel, state->code);          // settle on the real code
            ffx_sceneLabel_setTextColor(state->codeLabel, COLOR_ORANGE);
        } else if (now - state->lastScramble >= SCRAMBLE_STEP_MS) {
            state->lastScramble = now;
            setCodeText(state->codeLabel, (uint16_t)(esp_random() % 10000));
        }
    }

    if (!state->decided && (now - state->startTicks) >= APPROVAL_TIMEOUT_MS) {
        decide(state, TreasuryOutcomeExpired);
    }
}

static FfxNode label(FfxScene scene, FfxNode parent, FfxFont font,
  color_ffxt color, int16_t x, int16_t y, const char *text) {
    FfxNode node = ffx_scene_createLabel(scene, font, text);
    ffx_sceneGroup_appendChild(parent, node);
    ffx_sceneLabel_setAlign(node, FfxTextAlignMiddle | FfxTextAlignCenter);
    ffx_sceneLabel_setTextColor(node, color);
    ffx_sceneNode_setPosition(node, ffx_point(x, y));
    return node;
}

static int initFunc(FfxScene scene, FfxNode node, void *_state, void *initArg) {
    TxState *state = _state;
    state->req = *(const ApproveRequest *)initArg;   // deep copy
    const ApproveRequest *req = &state->req;
    state->code = req->match_code;                   // precomputed by the serial task

    char amount[48], dest[24];
    snprintf(amount, sizeof(amount), "%.2f %s", req->amount, req->currency);
    shortenAddress(req->dest, dest, sizeof(dest));

    label(scene, node, FfxFontSmallBold, COLOR_STONE,  120,  20, "VERIFY PAYMENT");
    label(scene, node, FfxFontMediumBold, COLOR_PAPER, 120,  50, amount);
    label(scene, node, FfxFontSmall,     COLOR_STONE,  120,  74, dest);
    label(scene, node, FfxFontSmall,     COLOR_STONE,  120,  92, req->network);

    // Match-code "chip": dark surface with an orange accent bar.
    FfxNode chip = ffx_scene_createBox(scene, ffx_size(CHIP_W, CHIP_H));
    ffx_sceneBox_setColor(chip, ffx_color_rgb(0x21, 0x1d, 0x1b));
    ffx_sceneNode_setPosition(chip, ffx_point(CHIP_X, CHIP_Y));
    ffx_sceneGroup_appendChild(node, chip);

    FfxNode bar = ffx_scene_createBox(scene, ffx_size(CHIP_W, 3));
    ffx_sceneBox_setColor(bar, COLOR_ORANGE);
    ffx_sceneNode_setPosition(bar, ffx_point(CHIP_X, CHIP_Y));
    ffx_sceneGroup_appendChild(node, bar);

    label(scene, node, FfxFontSmall, COLOR_STONE, 120, 112, "MATCH CODE");
    state->codeLabel = label(scene, node, FfxFontLargeBold, COLOR_ORANGE,
      120, CHIP_Y + CHIP_H / 2 + 4, "");
    setCodeText(state->codeLabel, state->code);

    label(scene, node, FfxFontSmall,     COLOR_STONE, 120, 192, "SW2 refresh code");
    label(scene, node, FfxFontSmallBold, COLOR_GO,     66, 218, "SW4 APPROVE");
    label(scene, node, FfxFontSmallBold, COLOR_STOP,  174, 218, "SW1 REJECT");

    ffx_onEvent(FfxEventKeys, onKeys, state);
    ffx_onEvent(FfxEventRenderScene, onRender, state);
    return 0;
}

int pushPanelTransaction(const ApproveRequest *req) {
    return ffx_pushPanel(initFunc, sizeof(TxState), (void *)req);
}
