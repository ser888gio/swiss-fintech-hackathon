#include "firefly-hollows.h"
#include "firefly-scene.h"

#include "panels.h"

// Screen 3 — Result.
//
// Shown after the operator approves, rejects, or lets the transaction expire.
// Displays a large status word (APPROVED / REJECTED / EXPIRED) in the
// appropriate safety colour, then auto-dismisses after AUTO_DISMISS_MS so
// the device returns to standby without requiring a button press.

#define AUTO_DISMISS_MS  (2500)

typedef struct {
    TreasuryOutcome outcome;
    bool            started;
    uint32_t        startTicks;
} ResultState;

static void onRender(FfxEvent event, FfxEventProps props, void *arg) {
    ResultState *state = arg;
    uint32_t now = props.render.ticks;

    if (!state->started) { state->started = true; state->startTicks = now; }

    if ((now - state->startTicks) >= AUTO_DISMISS_MS) {
        ffx_popPanel(0);
    }
}

static void label(FfxScene scene, FfxNode parent, FfxFont font,
  color_ffxt color, int16_t y, const char *text) {
    FfxNode node = ffx_scene_createLabel(scene, font, text);
    ffx_sceneGroup_appendChild(parent, node);
    ffx_sceneLabel_setAlign(node, FfxTextAlignMiddle | FfxTextAlignCenter);
    ffx_sceneLabel_setTextColor(node, color);
    ffx_sceneNode_setPosition(node, ffx_point(120, y));
}

static int initFunc(FfxScene scene, FfxNode node, void *_state, void *initArg) {
    ResultState *state = _state;
    state->outcome = (TreasuryOutcome)(intptr_t)initArg;

    const char *word;
    color_ffxt  color;
    const char *sub;

    switch (state->outcome) {
        case TreasuryOutcomeApproved:
            word  = "APPROVED";
            color = COLOR_GO;
            sub   = "Signing…";
            break;
        case TreasuryOutcomeExpired:
            word  = "EXPIRED";
            color = COLOR_STONE;
            sub   = "No decision in time";
            break;
        case TreasuryOutcomeRejected:
        default:
            word  = "REJECTED";
            color = COLOR_STOP;
            sub   = "Payment blocked";
            break;
    }

    label(scene, node, FfxFontSmallBold,  COLOR_STONE, 68,  "TREASURY VETO");
    label(scene, node, FfxFontLargeBold,  color,       120, word);
    label(scene, node, FfxFontSmall,      COLOR_STONE, 158, sub);

    ffx_onEvent(FfxEventRenderScene, onRender, state);
    return 0;
}

int pushPanelResult(TreasuryOutcome outcome) {
    return ffx_pushPanel(initFunc, sizeof(ResultState), (void *)(intptr_t)outcome);
}
