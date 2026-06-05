#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "esp_ble_mesh_defs.h"
#include "esp_ble_mesh_provisioning_api.h"
#include "sensors.h"
#include "config.h"

/*
 * Vendor model opcodes (3-byte format: 0xC? then 2-byte CID little-endian).
 * ESP_BLE_MESH_MODEL_OP_3(opcode_byte, company_id)
 */
#define OP_SENSOR_DATA  ESP_BLE_MESH_MODEL_OP_3(0xC0, PHYTOSENSE_CID)
#define OP_GRADIENT_ADV ESP_BLE_MESH_MODEL_OP_3(0xC1, PHYTOSENSE_CID)
#define OP_GRADIENT_SET ESP_BLE_MESH_MODEL_OP_3(0xC2, PHYTOSENSE_CID)

/* Sensor data packet forwarded hop-by-hop toward the hub */
typedef struct __attribute__((packed)) {
    uint8_t  origin_node_id;      /* node that sensed the data              */
    uint8_t  origin_gradient;     /* gradient level of that node            */
    uint8_t  hop_count;           /* incremented at each relay              */
    uint32_t timestamp_s;         /* seconds since origin node boot         */
    float    temperature_c;
    float    humidity_pct;
    float    soil_moisture_pct;
} sensor_data_msg_t;   /* 23 bytes */

/* Periodic advertisement: node announces its gradient so neighbours can build
   their routing table without provisioner involvement */
typedef struct __attribute__((packed)) {
    uint8_t node_id;
    uint8_t gradient;
} gradient_adv_msg_t;   /* 2 bytes */

/* Hub can push a corrected gradient to a specific node */
typedef struct __attribute__((packed)) {
    uint8_t target_node_id;
    uint8_t new_gradient;
} gradient_set_msg_t;   /* 2 bytes */

typedef void (*prov_cb_t)(esp_ble_mesh_prov_cb_event_t,
                          esp_ble_mesh_prov_cb_param_t *);
typedef void (*model_cb_t)(esp_ble_mesh_model_cb_event_t,
                           esp_ble_mesh_model_cb_param_t *);

esp_err_t gradient_mesh_init(uint8_t node_id, uint8_t gradient,
                              uint8_t dev_uuid[16],
                              prov_cb_t prov_cb, model_cb_t model_cb);

void gradient_mesh_set_provisioned(uint16_t unicast_addr);
void gradient_mesh_publish_sensor(const sensor_reading_t *reading);
void gradient_mesh_advertise_level(void);
void gradient_mesh_on_receive(uint16_t src_addr, uint32_t opcode,
                               const uint8_t *data, uint16_t len,
                               int8_t rssi);
uint8_t gradient_mesh_get_level(void);
bool    gradient_mesh_is_provisioned(void);
