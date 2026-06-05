#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "esp_log.h"
#include "esp_bt.h"
#include "esp_bluedroid_init_ctx.h"
#include "nvs_flash.h"
#include "esp_ble_mesh_defs.h"
#include "esp_ble_mesh_provisioning_api.h"

#include "config.h"
#include "topology.h"
#include "sensors.h"
#include "gradient_mesh.h"

#define TAG "main"

/*
 * Device UUID: first byte = NODE_ID so the provisioner can identify each node
 * without needing a separate lookup table.
 */
static uint8_t s_uuid[16] = {
    NODE_ID, 0x50, 0x68, 0x79, 0x74, 0x6f,   /* 'Phyto' */
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

static TimerHandle_t s_sensor_tmr;
static TimerHandle_t s_nbr_adv_tmr;

static void sensor_tmr_cb(TimerHandle_t t)
{
    sensor_reading_t r;
    if (sensors_read(&r) == ESP_OK)
        gradient_mesh_publish_sensor(&r);
}

static void nbr_adv_tmr_cb(TimerHandle_t t)
{
    gradient_mesh_advertise_level();
}

static void prov_cb(esp_ble_mesh_prov_cb_event_t ev,
                    esp_ble_mesh_prov_cb_param_t *p)
{
    if (ev == ESP_BLE_MESH_NODE_PROV_COMPLETE_EVT) {
        ESP_LOGI(TAG, "Provisioned  net_idx=%u  addr=0x%04x",
                 p->node_prov_complete.net_idx,
                 p->node_prov_complete.addr);
        gradient_mesh_set_provisioned(p->node_prov_complete.addr);
    }
}

static void model_cb(esp_ble_mesh_model_cb_event_t ev,
                     esp_ble_mesh_model_cb_param_t *p)
{
    if (ev == ESP_BLE_MESH_MODEL_OPERATION_EVT) {
        gradient_mesh_on_receive(
            p->model_operation.ctx->addr,
            p->model_operation.opcode,
            p->model_operation.msg,
            p->model_operation.length,
            p->model_operation.ctx->recv_rssi
        );
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "PhytoSense node_id=%d  gradient=%d  booting...",
             NODE_ID, GRADIENT_LEVEL);

    /* NVS */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    /* Bluetooth controller */
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_BLE));

    /* Bluedroid stack */
    esp_bluedroid_config_t bd_cfg = BT_BLUEDROID_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bluedroid_init_with_cfg(&bd_cfg));
    ESP_ERROR_CHECK(esp_bluedroid_enable());

    /* Sensor hardware (hub node 0 skips this) */
    if (NODE_ID != 0)
        ESP_ERROR_CHECK(sensors_init());

    /* Gradient mesh */
    ESP_ERROR_CHECK(gradient_mesh_init(NODE_ID, GRADIENT_LEVEL,
                                        s_uuid, prov_cb, model_cb));

    /* Periodic sensor reads – first reading 15 s after boot to let mesh settle */
    if (NODE_ID != 0) {
        s_sensor_tmr = xTimerCreate("sensor",
                                     pdMS_TO_TICKS(SENSOR_INTERVAL_MS),
                                     pdTRUE, NULL, sensor_tmr_cb);
        xTimerStart(s_sensor_tmr, pdMS_TO_TICKS(15000));
    }

    /* Neighbour advertisements – start immediately */
    s_nbr_adv_tmr = xTimerCreate("nbr_adv",
                                   pdMS_TO_TICKS(NEIGHBOR_ADV_MS),
                                   pdTRUE, NULL, nbr_adv_tmr_cb);
    xTimerStart(s_nbr_adv_tmr, pdMS_TO_TICKS(1000));

    ESP_LOGI(TAG, "Init complete – waiting for provisioner");
}
