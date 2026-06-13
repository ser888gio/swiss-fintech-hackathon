#include <stdio.h>
#include <string.h>

#include "firefly-hollows.h"
#include "panel_approve.h"

#define COLOR_APPROVE  0x22AA44FF
#define COLOR_REJECT   0xCC2200FF

// Panel state — holds a copy of the request so it remains valid after
// pushPanelApprove returns (the caller's ApproveRequest may be on the stack).
typedef struct {
    ApproveRequest req;
} ApproveState;

static void onClick(void *_state, FfxInfoClickArg clickArg) {
    int result = clickArg.a.i32;
    xQueueSend(g_approval_queue, &result, 0);
    ffx_popPanel(result);
}

static int infoInit(void *info, void *_state, void *_initArg) {
    ApproveState *state = _state;
    state->req = *(const ApproveRequest *)_initArg;   // deep copy into panel state
    const ApproveRequest *req = &state->req;

    char amount_str[48];
    snprintf(amount_str, sizeof(amount_str), "%.2f %s", req->amount, req->currency);

    char dest_short[24], owner_short[24], tx_short[34], seq_str[16];
    snprintf(dest_short,  sizeof(dest_short),  "%.22s", req->dest);
    snprintf(owner_short, sizeof(owner_short), "%.22s", req->owner);
    snprintf(tx_short,    sizeof(tx_short),    "%.32s", req->escrow_create_tx_hash);
    snprintf(seq_str,     sizeof(seq_str),     "%lu",   (unsigned long)req->escrow_sequence);

    ffx_appendInfoEntry(info, "Network",    req->network, NULL, (FfxInfoClickArg){0});
    ffx_appendInfoEntry(info, "Amount",     amount_str,   NULL, (FfxInfoClickArg){0});
    ffx_appendInfoEntry(info, "To",         dest_short,   NULL, (FfxInfoClickArg){0});
    ffx_appendInfoEntry(info, "Owner",      owner_short,  NULL, (FfxInfoClickArg){0});
    ffx_appendInfoEntry(info, "Escrow seq", seq_str,      NULL, (FfxInfoClickArg){0});
    ffx_appendInfoEntry(info, "Escrow tx",  tx_short,     NULL, (FfxInfoClickArg){0});

    if (req->reference[0]) {
        ffx_appendInfoEntry(info, "Ref", req->reference, NULL, (FfxInfoClickArg){0});
    }

    FfxInfoClickArg approve_arg = { .a = { .i32 = 1 } };
    FfxInfoClickArg reject_arg  = { .a = { .i32 = 0 } };
    ffx_appendInfoButton(info, "APPROVE", COLOR_APPROVE, onClick, approve_arg);
    ffx_appendInfoButton(info, "REJECT",  COLOR_REJECT,  onClick, reject_arg);

    return 0;
}

int pushPanelApprove(const ApproveRequest *req) {
    return ffx_pushInfo(infoInit, "Treasury Veto", sizeof(ApproveState), (void *)req);
}
