#include "firefly-hollows.h"
#include "panel_approve.h"

// Called on every render tick. Non-blocking queue poll: safe to call from the
// Hollows UI task. When a request arrives, push the approval panel — which
// suspends this panel's events until it pops, preventing double-push.
static void onRender(FfxEvent event, FfxEventProps props, void *arg) {
    ApproveRequest req;
    if (xQueueReceive(g_request_queue, &req, 0) == pdTRUE) {
        pushPanelApprove(&req);
    }
}

static int initFunc(FfxScene scene, FfxNode node, void *state, void *initArg) {
    FfxNode label1 = ffx_scene_createLabel(scene, FfxFontLarge, "Waiting for");
    ffx_sceneGroup_appendChild(node, label1);
    ffx_sceneNode_setPosition(label1, (FfxPoint){ .x = 120, .y = 100 });
    ffx_sceneLabel_setAlign(label1, FfxTextAlignCenter);

    FfxNode label2 = ffx_scene_createLabel(scene, FfxFontLarge, "approval...");
    ffx_sceneGroup_appendChild(node, label2);
    ffx_sceneNode_setPosition(label2, (FfxPoint){ .x = 120, .y = 130 });
    ffx_sceneLabel_setAlign(label2, FfxTextAlignCenter);

    ffx_onEvent(FfxEventRenderScene, onRender, NULL);

    return 0;
}

int pushPanelWait(void) {
    return ffx_pushPanel(initFunc, 0, NULL);
}
