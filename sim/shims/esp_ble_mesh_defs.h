#pragma once
#include <stdint.h>

/* ---- Address constants ---- */
#define ESP_BLE_MESH_ADDR_UNASSIGNED  0x0000u
#define BLE_MESH_TTL_DEFAULT          7

/*
 * 3-byte vendor opcode encoding: (opcode_byte << 16) | company_id
 * Matches the encoding used on-device so the same opcode constants
 * work in gradient_mesh.h, transport.c, and broker.py.
 *
 *   OP_SENSOR_DATA  = (0xC0 << 16) | 0x05C3 = 0x00C005C3
 *   OP_GRADIENT_ADV = (0xC1 << 16) | 0x05C3 = 0x00C105C3
 *   OP_GRADIENT_SET = (0xC2 << 16) | 0x05C3 = 0x00C205C3
 */
#define ESP_BLE_MESH_MODEL_OP_3(b0, cid) \
    ((uint32_t)(((uint32_t)(b0) << 16) | ((uint32_t)(cid) & 0xFFFFu)))

/*
 * Provisioning callback types – only used in gradient_mesh_init's signature.
 * Under HOST_SIM, gradient_mesh_init ignores the callbacks entirely, so
 * these are stub types that satisfy the compiler without pulling in the SDK.
 */
typedef int  esp_ble_mesh_prov_cb_event_t;
typedef void esp_ble_mesh_prov_cb_param_t;
typedef int  esp_ble_mesh_model_cb_event_t;
typedef void esp_ble_mesh_model_cb_param_t;

/* Provision enable flags (referenced in gradient_mesh.h typedef, not called) */
#define ESP_BLE_MESH_PROV_ADV  0x01
#define ESP_BLE_MESH_PROV_GATT 0x02
