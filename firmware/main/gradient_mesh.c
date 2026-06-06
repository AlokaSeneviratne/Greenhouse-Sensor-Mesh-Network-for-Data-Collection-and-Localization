#include "gradient_mesh.h"
#include "topology.h"
#include "esp_log.h"
#include "esp_ble_mesh_common_api.h"
#include "esp_ble_mesh_networking_api.h"
#include "esp_ble_mesh_provisioning_api.h"
#include "esp_ble_mesh_config_model_api.h"
#include "esp_timer.h"
#include <string.h>
#include <stdio.h>

#ifdef HOST_SIM
#include "transport.h"
#endif

#define TAG "gradient_mesh"

/* ---- Neighbour table ---- */

typedef struct {
    uint16_t addr;
    uint8_t  gradient;
    int8_t   rssi;
    uint64_t last_seen_us;
} neighbour_t;

static neighbour_t s_nbrs[MAX_NEIGHBORS];
static uint8_t     s_node_id;
static uint8_t     s_gradient;
static uint16_t    s_unicast;
static bool        s_provisioned;

#ifndef HOST_SIM
/* ---- BLE Mesh model composition (device build only) ---- */

static esp_ble_mesh_model_op_t s_vnd_ops[] = {
    ESP_BLE_MESH_MODEL_OP(OP_SENSOR_DATA,  sizeof(sensor_data_msg_t)),
    ESP_BLE_MESH_MODEL_OP(OP_GRADIENT_ADV, sizeof(gradient_adv_msg_t)),
    ESP_BLE_MESH_MODEL_OP(OP_GRADIENT_SET, sizeof(gradient_set_msg_t)),
    ESP_BLE_MESH_MODEL_OP_END,
};

static esp_ble_mesh_model_t s_root_models[] = {
    ESP_BLE_MESH_MODEL_CFG_SRV,
};

static esp_ble_mesh_model_t s_vnd_models[] = {
    ESP_BLE_MESH_VENDOR_MODEL(PHYTOSENSE_CID, PHYTOSENSE_VENDOR_MOD,
                               s_vnd_ops, NULL, NULL),
};

static esp_ble_mesh_elem_t s_elements[] = {
    ESP_BLE_MESH_ELEMENT(0, s_root_models, s_vnd_models),
};

static esp_ble_mesh_comp_t s_comp = {
    .cid           = PHYTOSENSE_CID,
    .pid           = 0x0001,
    .vid           = 0x0001,
    .element_count = sizeof(s_elements) / sizeof(s_elements[0]),
    .elements      = s_elements,
};

/* Pre-shared keys embedded at compile time */
static uint8_t s_net_key[16] = MESH_NET_KEY;
static uint8_t s_app_key[16] = MESH_APP_KEY;
#endif /* HOST_SIM */

/* ---- Neighbour table helpers ---- */

static void nbr_update(uint16_t addr, uint8_t gradient, int8_t rssi)
{
    uint64_t now = esp_timer_get_time();
    int empty = -1;

    for (int i = 0; i < MAX_NEIGHBORS; i++) {
        if (s_nbrs[i].addr == addr) {
            s_nbrs[i].gradient    = gradient;
            s_nbrs[i].rssi        = rssi;
            s_nbrs[i].last_seen_us = now;
            return;
        }
        if (!s_nbrs[i].addr && empty < 0) empty = i;
    }

    if (empty < 0) {
        /* Evict the stalest entry */
        for (int i = 1; i < MAX_NEIGHBORS; i++)
            if (s_nbrs[i].last_seen_us < s_nbrs[empty < 0 ? (empty = 0) : empty].last_seen_us)
                empty = i;
    }

    s_nbrs[empty] = (neighbour_t){ addr, gradient, rssi, now };
    ESP_LOGD(TAG, "nbr+ 0x%04x g=%d rssi=%d", addr, gradient, rssi);
}

/*
 * Select the parent to forward toward.
 * Rule: pick the neighbour with the smallest gradient < own gradient.
 * Ties broken by highest RSSI (physically closest).
 * Falls back to HUB_UNICAST_ADDR if this is a gradient-1 node with no
 * neighbour table entry for the hub yet.
 */
static uint16_t best_parent(void)
{
    uint64_t now      = esp_timer_get_time();
    uint16_t best_a   = ESP_BLE_MESH_ADDR_UNASSIGNED;
    uint8_t  best_g   = s_gradient;   /* must be strictly lower */
    int8_t   best_r   = -128;

    for (int i = 0; i < MAX_NEIGHBORS; i++) {
        neighbour_t *n = &s_nbrs[i];
        if (!n->addr) continue;
        if ((now - n->last_seen_us) > (uint64_t)NEIGHBOR_TIMEOUT_MS * 1000) continue;
        if (n->gradient >= s_gradient) continue;

        if (n->gradient < best_g || (n->gradient == best_g && n->rssi > best_r)) {
            best_g = n->gradient;
            best_r = n->rssi;
            best_a = n->addr;
        }
    }

    /* Gradient-1 nodes always have a direct path to the hub */
    if (best_a == ESP_BLE_MESH_ADDR_UNASSIGNED && s_gradient == 1)
        best_a = HUB_UNICAST_ADDR;

    return best_a;
}

/* ---- Send helper ---- */

static esp_err_t mesh_send(uint16_t dst, uint32_t opcode,
                            const void *data, size_t len)
{
    if (!s_provisioned) return ESP_ERR_INVALID_STATE;

#ifndef HOST_SIM
    esp_ble_mesh_msg_ctx_t ctx = {
        .net_idx  = 0,
        .app_idx  = 0,
        .addr     = dst,
        .send_ttl = BLE_MESH_TTL_DEFAULT,
    };
    return esp_ble_mesh_server_model_send_msg(
               &s_vnd_models[0], &ctx, opcode,
               (uint16_t)len, (uint8_t *)data);
#else
    return transport_send(s_unicast, dst, opcode, data, len);
#endif
}

/* ---- Public API ---- */

esp_err_t gradient_mesh_init(uint8_t node_id, uint8_t gradient,
                              uint8_t dev_uuid[16],
                              prov_cb_t prov_cb, model_cb_t model_cb)
{
    s_node_id     = node_id;
    s_gradient    = gradient;
    s_unicast     = node_id_to_unicast(node_id);
    s_provisioned = false;
    memset(s_nbrs, 0, sizeof(s_nbrs));

#ifndef HOST_SIM
    esp_ble_mesh_prov_t prov = {
        .uuid           = dev_uuid,
        .static_val     = s_net_key,
        .static_val_len = 16,
        .output_size    = 0,
        .input_size     = 0,
    };

    ESP_ERROR_CHECK(esp_ble_mesh_register_prov_callback(prov_cb));
    ESP_ERROR_CHECK(esp_ble_mesh_register_custom_model_callback(model_cb));

    esp_err_t ret = esp_ble_mesh_init(&prov, &s_comp);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "mesh init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_ERROR_CHECK(esp_ble_mesh_node_prov_enable(
        ESP_BLE_MESH_PROV_ADV | ESP_BLE_MESH_PROV_GATT));

    ESP_LOGI(TAG, "Node %d (g=%d) advertising for provisioning", node_id, gradient);
#else
    (void)dev_uuid; (void)prov_cb; (void)model_cb;
    ESP_LOGI(TAG, "Node %d (g=%d) sim init OK", node_id, gradient);
#endif

    return ESP_OK;
}

void gradient_mesh_set_provisioned(uint16_t unicast_addr)
{
    s_unicast     = unicast_addr;
    s_provisioned = true;
    ESP_LOGI(TAG, "Provisioned: 0x%04x  gradient=%d", unicast_addr, s_gradient);
}

void gradient_mesh_publish_sensor(const sensor_reading_t *r)
{
    if (!s_provisioned) return;

    uint16_t parent = best_parent();
    if (parent == ESP_BLE_MESH_ADDR_UNASSIGNED) {
        ESP_LOGW(TAG, "Node %d: no parent found, holding packet", s_node_id);
        return;
    }

    sensor_data_msg_t msg = {
        .origin_node_id    = s_node_id,
        .origin_gradient   = s_gradient,
        .hop_count         = 0,
        .timestamp_s       = r->timestamp_s,
        .temperature_c     = r->temperature_c,
        .humidity_pct      = r->humidity_pct,
        .soil_moisture_pct = r->soil_moisture_pct,
    };

    ESP_LOGI(TAG, "Node %d → 0x%04x  T=%.1f H=%.1f S=%.1f",
             s_node_id, parent,
             msg.temperature_c, msg.humidity_pct, msg.soil_moisture_pct);

    mesh_send(parent, OP_SENSOR_DATA, &msg, sizeof(msg));
}

void gradient_mesh_advertise_level(void)
{
    if (!s_provisioned) return;
    gradient_adv_msg_t adv = { s_node_id, s_gradient };
    mesh_send(PHYTOSENSE_GROUP_ADDR, OP_GRADIENT_ADV, &adv, sizeof(adv));
}

void gradient_mesh_on_receive(uint16_t src_addr, uint32_t opcode,
                               const uint8_t *data, uint16_t len,
                               int8_t rssi)
{
    if (opcode == OP_GRADIENT_ADV) {
        if (len < (uint16_t)sizeof(gradient_adv_msg_t)) return;
        const gradient_adv_msg_t *adv = (const gradient_adv_msg_t *)data;
        nbr_update(src_addr, adv->gradient, rssi);

    } else if (opcode == OP_GRADIENT_SET) {
        if (len < (uint16_t)sizeof(gradient_set_msg_t)) return;
        const gradient_set_msg_t *gs = (const gradient_set_msg_t *)data;
        if (gs->target_node_id == s_node_id) {
            ESP_LOGI(TAG, "Gradient updated by hub: %d → %d",
                     s_gradient, gs->new_gradient);
            s_gradient = gs->new_gradient;
        }

    } else if (opcode == OP_SENSOR_DATA) {
        if (len < (uint16_t)sizeof(sensor_data_msg_t)) return;
        sensor_data_msg_t *msg = (sensor_data_msg_t *)data;

        if (s_gradient == 0) {
            /*
             * Hub: emit JSON on UART so gateway.py can read it.
             * Format: {"node":N,"t":T,"h":H,"s":S,"hops":N,"ts":N}
             */
            printf("{\"node\":%u,\"t\":%.2f,\"h\":%.2f,\"s\":%.2f"
                   ",\"hops\":%u,\"ts\":%lu}\n",
                   msg->origin_node_id,
                   msg->temperature_c,
                   msg->humidity_pct,
                   msg->soil_moisture_pct,
                   msg->hop_count,
                   (unsigned long)msg->timestamp_s);
        } else {
            /* Relay: increment hop count and forward toward centre */
            uint16_t parent = best_parent();
            if (parent == ESP_BLE_MESH_ADDR_UNASSIGNED) {
                ESP_LOGW(TAG, "Node %d: no parent to relay for node %d",
                         s_node_id, msg->origin_node_id);
                return;
            }
            msg->hop_count++;
            ESP_LOGD(TAG, "Relay node%d → 0x%04x (hop %d)",
                     msg->origin_node_id, parent, msg->hop_count);
            mesh_send(parent, OP_SENSOR_DATA, msg, sizeof(*msg));
        }
    }
}

uint8_t gradient_mesh_get_level(void)    { return s_gradient; }
bool    gradient_mesh_is_provisioned(void) { return s_provisioned; }
