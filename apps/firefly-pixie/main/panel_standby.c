#include "firefly-hollows.h"
#include "firefly-scene.h"

#include "panels.h"

// Screen 1 — Standby.
//
// The root panel. On every render tick it (a) breathes a small accent indicator
// so the operator can see the device is live, and (b) polls g_request_queue.
// When the bridge forwards a payment, it pushes the transaction screen, which
// blocks (its own task) until the operator decides; control then returns here,
// ready for the next payment. This panel never pops.

#define DOT_SIZE   (14)

typedef struct {
    FfxNode dot;   // pulsing "live" indicator
} StandbyState;

static void onRender(FfxEvent event, FfxEventProps props, void *arg) {
    StandbyState *state = arg;

    // Breathe the live indicator over a 2s triangle wave (opacity 6→32→6).
    uint32_t t = props.render.ticks % 2000;
    uint32_t phase = (t < 1000) ? t : (2000 - t);
    uint8_t opacity = OPACITY_20 + (uint8_t)((phase * (OPACITY_100 - OPACITY_20)) / 1000);
    ffx_sceneBox_setOpacity(state->dot, opacity);

    // Non-blocking poll. pushPanelTransaction blocks until the decision is made,
    // so this only fires once per payment.
    ApproveRequest req;
    if (xQueueReceive(g_request_queue, &req, 0) == pdTRUE) {
        pushPanelTransaction(&req);
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
    StandbyState *state = _state;

    label(scene, node, FfxFontSmallBold, COLOR_STONE,  68, "TREASURY VETO");
    label(scene, node, FfxFontLargeBold, COLOR_PAPER, 110, "STANDBY");

    FfxNode dot = ffx_scene_createBox(scene, ffx_size(DOT_SIZE, DOT_SIZE));
    ffx_sceneBox_setColor(dot, COLOR_ORANGE_BRIGHT);
    ffx_sceneNode_setPosition(dot, ffx_point(120 - DOT_SIZE / 2, 150));
    ffx_sceneGroup_appendChild(node, dot);
    state->dot = dot;

    label(scene, node, FfxFontSmall, COLOR_STONE, 186, "Waiting for transaction");

    ffx_onEvent(FfxEventRenderScene, onRender, state);
    return 0;
}

int pushPanelStandby(void) {
    return ffx_pushPanel(initFunc, sizeof(StandbyState), NULL);
}
