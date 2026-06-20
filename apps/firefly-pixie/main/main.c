#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "nvs_flash.h"
#include "nvs.h"
#include "esp_random.h"
#include "driver/usb_serial_jtag.h"
#include "cJSON.h"

#include "firefly-hollows.h"
#include "firefly-ecc.h"
#include "firefly-hash.h"

#include "panels.h"

#define NVS_NAMESPACE     "treasury"
#define NVS_KEY_PRIVKEY   "privkey"
#define SERIAL_BUF_SIZE   2048
#define PAYLOAD_BUF_SIZE  1024
#define SERIAL_TASK_STACK 8192

// Queues defined here; externed via panel_approve.h.
QueueHandle_t g_request_queue;
QueueHandle_t g_approval_queue;

static FfxEcPrivkey s_privkey;

// ── Helpers ───────────────────────────────────────────────────────────────────

static void bytes_to_hex(const uint8_t *data, size_t len, char *out) {
    for (size_t i = 0; i < len; i++) {
        sprintf(out + i * 2, "%02x", data[i]);
    }
    out[len * 2] = '\0';
}

// Write a response back to the bridge over the same USB-Serial-JTAG port we
// read from. printf goes to the console (UART0), not this port.
static void serial_reply(const char *line) {
    size_t len = strlen(line);
    usb_serial_jtag_write_bytes((const uint8_t *)line, len,  pdMS_TO_TICKS(200));
    usb_serial_jtag_write_bytes((const uint8_t *)"\n",  1,   pdMS_TO_TICKS(200));
}

// ── Key management ────────────────────────────────────────────────────────────

static esp_err_t load_or_generate_key(void) {
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;

    size_t len = sizeof(s_privkey.data);
    err = nvs_get_blob(nvs, NVS_KEY_PRIVKEY, s_privkey.data, &len);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        esp_fill_random(s_privkey.data, sizeof(s_privkey.data));
        err = nvs_set_blob(nvs, NVS_KEY_PRIVKEY, s_privkey.data, sizeof(s_privkey.data));
        if (err == ESP_OK) err = nvs_commit(nvs);
        if (err == ESP_OK) printf("[treasury] Generated new secp256k1 key\n");
    }
    nvs_close(nvs);
    return err;
}

static void print_public_key(void) {
    FfxEcPubkey pubkey;
    ffx_ec_computePubkey(&pubkey, &s_privkey);
    // pubkey.data[0] is the 0x04 uncompressed prefix; bridge expects 64 bytes without it.
    char hex[129];
    bytes_to_hex(pubkey.data + 1, 64, hex);
    printf("[treasury] FIREFLY_PUBLIC_KEY=%s\n", hex);
}

// ── Canonical payload + digest + match code ─────────────────────────────────────
//
// MUST stay byte-for-byte identical to apps/api/app/tools/firefly.py::canonical_payload
// and apps/firefly-bridge/src/device.ts::deriveDigest.

size_t treasury_canonical_payload(const ApproveRequest *req, char *out, size_t out_len) {
    int len = snprintf(out, out_len,
        "XRPL_TREASURY_APPROVAL_V1|%s|%s|%s|%s|%s|%.2f|%lu|%s",
        req->network,
        req->payment_id,
        req->owner,
        req->dest,
        req->currency,
        req->amount,
        (unsigned long)req->escrow_sequence,
        req->escrow_create_tx_hash
    );
    if (len < 0 || len >= (int)out_len) { return 0; }
    return (size_t)len;
}

// 4-digit visual match code: first 4 bytes of the canonical digest, big-endian,
// mod 10000. The bridge (device.ts) and backend (firefly.py) use the identical
// formula so the operator can confirm the device and dashboard agree. Display
// only — the secp256k1 signature over the canonical payload still releases.
//
// NOTE: uses a 1KB stack buffer, so call it only from a generously-sized stack
// (the serial task, not a ~4KB Hollows panel task — that overflows and panics).
uint16_t treasury_match_code(const ApproveRequest *req) {
    char payload[PAYLOAD_BUF_SIZE];
    size_t len = treasury_canonical_payload(req, payload, sizeof(payload));
    if (len == 0) { return 0; }

    FfxEcDigest digest;
    ffx_hash_sha256(digest.data, (const uint8_t *)payload, len);
    uint32_t v = ((uint32_t)digest.data[0] << 24) | ((uint32_t)digest.data[1] << 16) |
                 ((uint32_t)digest.data[2] << 8)  |  (uint32_t)digest.data[3];
    return (uint16_t)(v % 10000);
}

static void compute_digest(const ApproveRequest *req, FfxEcDigest *out) {
    char payload[PAYLOAD_BUF_SIZE];
    size_t len = treasury_canonical_payload(req, payload, sizeof(payload));
    if (len == 0) {
        memset(out->data, 0, sizeof(out->data));
        return;
    }
    ffx_hash_sha256(out->data, (const uint8_t *)payload, len);
}

// ── JSON parsing ──────────────────────────────────────────────────────────────

static bool parse_sign_request(const char *json_str, ApproveRequest *out) {
    bool ok = false;
    cJSON *root = cJSON_Parse(json_str);
    if (!root) return false;

    cJSON *cmd_j     = cJSON_GetObjectItemCaseSensitive(root, "cmd");
    cJSON *display_j = cJSON_GetObjectItemCaseSensitive(root, "display");
    if (!cJSON_IsString(cmd_j) || strcmp(cmd_j->valuestring, "sign") != 0) goto done;
    if (!cJSON_IsObject(display_j)) goto done;

#define GET_S(key, dst, size) do { \
    cJSON *_f = cJSON_GetObjectItemCaseSensitive(display_j, (key)); \
    if (!cJSON_IsString(_f)) goto done; \
    strncpy((dst), _f->valuestring, (size) - 1); (dst)[(size) - 1] = '\0'; \
} while (0)

    GET_S("paymentId",          out->payment_id,            sizeof(out->payment_id));
    GET_S("network",            out->network,               sizeof(out->network));
    GET_S("owner",              out->owner,                 sizeof(out->owner));
    GET_S("dest",               out->dest,                  sizeof(out->dest));
    GET_S("currency",           out->currency,              sizeof(out->currency));
    GET_S("escrowCreateTxHash", out->escrow_create_tx_hash, sizeof(out->escrow_create_tx_hash));

#undef GET_S

    cJSON *amount_j = cJSON_GetObjectItemCaseSensitive(display_j, "amount");
    if (!cJSON_IsNumber(amount_j)) goto done;
    out->amount = amount_j->valuedouble;

    cJSON *seq_j = cJSON_GetObjectItemCaseSensitive(display_j, "escrowSequence");
    if (!cJSON_IsNumber(seq_j)) goto done;
    out->escrow_sequence = (uint32_t)seq_j->valuedouble;

    cJSON *ref_j = cJSON_GetObjectItemCaseSensitive(display_j, "reference");
    if (cJSON_IsString(ref_j)) {
        strncpy(out->reference, ref_j->valuestring, sizeof(out->reference) - 1);
    } else {
        out->reference[0] = '\0';
    }

    ok = true;
done:
    cJSON_Delete(root);
    return ok;
}

// ── Serial task ───────────────────────────────────────────────────────────────

static void serial_task(void *arg) {
    char line[SERIAL_BUF_SIZE];
    int pos = 0;

    while (1) {
        uint8_t ch;
        int n = usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(50));
        if (n <= 0) continue;

        if (ch == '\n' || ch == '\r') {
            if (pos == 0) continue;
            line[pos] = '\0';
            pos = 0;

            ApproveRequest req = {0};
            if (!parse_sign_request(line, &req)) {
                printf("[treasury] bad request\n");
                continue;
            }

            // Precompute the match code here (8KB stack) so the panel task — which
            // has only ~4KB — never runs the 1KB-buffer derivation itself.
            req.match_code = treasury_match_code(&req);

            // Hand to the standby panel via queue; it polls this each render tick.
            if (xQueueSend(g_request_queue, &req, pdMS_TO_TICKS(1000)) != pdTRUE) {
                serial_reply("{\"status\":\"error\",\"message\":\"device busy\"}");
                continue;
            }

            // Block until the operator decides. The transaction screen enforces a
            // 60s UI timeout and always queues a result (0 on reject/expire), so
            // this 90s wait is just an outer safety net, below the bridge's 120s.
            int approved = 0;
            if (xQueueReceive(g_approval_queue, &approved, pdMS_TO_TICKS(90000)) != pdTRUE) {
                serial_reply("{\"status\":\"error\",\"message\":\"approval timeout\"}");
                continue;
            }

            if (approved) {
                FfxEcDigest  digest;
                FfxEcSignature sig;
                compute_digest(&req, &digest);
                if (ffx_ec_signDigest(&sig, &s_privkey, &digest)) {
                    char sig_hex[131];
                    char reply[200];
                    bytes_to_hex(sig.data, sizeof(sig.data), sig_hex);
                    snprintf(reply, sizeof(reply),
                             "{\"status\":\"ok\",\"signature\":\"%s\"}", sig_hex);
                    serial_reply(reply);
                } else {
                    serial_reply("{\"status\":\"error\",\"message\":\"signing failed\"}");
                }
            } else {
                serial_reply("{\"status\":\"rejected\"}");
            }

        } else if (pos < SERIAL_BUF_SIZE - 1) {
            line[pos++] = (char)ch;
        }
    }
}

// ── Hollows entry point ───────────────────────────────────────────────────────

static int initPanel(void *arg) {
    return pushPanelStandby();
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(load_or_generate_key());

    uint8_t rnd[32];
    esp_fill_random(rnd, sizeof(rnd));
    ffx_ec_init(rnd);

    print_public_key();

    usb_serial_jtag_driver_config_t usb_cfg = {
        .rx_buffer_size = SERIAL_BUF_SIZE,
        .tx_buffer_size = SERIAL_BUF_SIZE,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_cfg));

    // Depth-1 queues: only one approval in flight at a time.
    g_request_queue  = xQueueCreate(1, sizeof(ApproveRequest));
    g_approval_queue = xQueueCreate(1, sizeof(int));

    xTaskCreate(serial_task, "serial", SERIAL_TASK_STACK, NULL, 4, NULL);

    vTaskSetApplicationTaskTag(NULL, (void*)NULL);
    // Pass NULL for the background: the framework then installs a full-screen
    // COLOR_BLACK fill that clears every fragment each frame. A non-NULL no-op
    // would leave the reused fragment buffers holding stale pixels.
    ffx_init(FFX_VERSION(0, 0, 1), NULL, initPanel, NULL);

    while (1) {
        ffx_dumpStats();
        vTaskDelay(pdMS_TO_TICKS(60000));
    }
}
