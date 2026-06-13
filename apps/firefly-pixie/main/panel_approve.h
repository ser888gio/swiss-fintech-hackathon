#pragma once

#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

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
} ApproveRequest;

// serial task → UI task: panel_wait polls this on each render tick.
extern QueueHandle_t g_request_queue;

// approval panel → serial task: sends 1 (approved) or 0 (rejected).
extern QueueHandle_t g_approval_queue;

// Push the approval info panel. req is copied into panel state inside initFunc
// so the caller's pointer does not need to outlive this call.
int pushPanelApprove(const ApproveRequest *req);
