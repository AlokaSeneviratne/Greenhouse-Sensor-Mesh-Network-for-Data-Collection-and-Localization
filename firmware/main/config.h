#pragma once

/* ---------- Per-node settings – change before flashing each device ---------- */
#define NODE_ID         1     /* 0 = hub ESP32, 1-20 = sensor nodes            */
#define GRADIENT_LEVEL  1     /* 0 = hub; see topology.h for the full map      */

/* ---------- I2C / SHT31-D ---------- */
#define I2C_PORT        0     /* I2C_NUM_0                                      */
#define SHT31_I2C_ADDR  0x44  /* ADDR pin low (factory default)                 */
#define SHT31_SDA_PIN   21
#define SHT31_SCL_PIN   22
#define I2C_FREQ_HZ     100000

/* ---------- Soil moisture ADC (GPIO34 = ADC1 channel 6) ---------- */
#define SOIL_ADC_CHANNEL  6   /* ADC1_CHANNEL_6                                 */
#define SOIL_ADC_ATTEN    3   /* ADC_ATTEN_DB_11  (0-3.9 V)                    */
#define SOIL_DRY_RAW   3000   /* ADC raw count when sensor is completely dry    */
#define SOIL_WET_RAW   1200   /* ADC raw count when sensor is saturated         */

/* ---------- BLE Mesh vendor model ---------- */
#define PHYTOSENSE_CID        0x05C3   /* Espressif test company ID             */
#define PHYTOSENSE_VENDOR_MOD 0x0001   /* PhytoSense sensor-relay model         */

/* Shared provisioning keys – all 20 nodes use the same pair */
#define MESH_NET_KEY  { 0x7d,0x27,0x62,0x87,0x72,0x68,0x83,0xef, \
                        0xb0,0x2e,0x6e,0x37,0x1a,0xf7,0x3b,0x01 }
#define MESH_APP_KEY  { 0x63,0x96,0x47,0x71,0x73,0x4f,0xbd,0x76, \
                        0xf0,0x69,0x60,0x97,0x42,0x12,0xa8,0xa4 }

/* ---------- Timing (milliseconds) ---------- */
#define SENSOR_INTERVAL_MS   60000  /* read sensors every 60 s                  */
#define NEIGHBOR_ADV_MS       5000  /* broadcast own gradient level every 5 s   */
#define NEIGHBOR_TIMEOUT_MS  30000  /* expire stale neighbor entries after 30 s  */

/* ---------- Mesh addresses ---------- */
#define HUB_UNICAST_ADDR      0x0001   /* hub ESP32 (gradient 0)                */
#define PHYTOSENSE_GROUP_ADDR 0xC000   /* all-nodes multicast group             */
#define MAX_NEIGHBORS            8
