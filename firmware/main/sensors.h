#pragma once
#include "esp_err.h"
#include <stdint.h>

typedef struct {
    float    temperature_c;
    float    humidity_pct;
    float    soil_moisture_pct;  /* 0.0 = bone dry, 100.0 = saturated */
    uint32_t timestamp_s;        /* seconds since node boot            */
} sensor_reading_t;

esp_err_t sensors_init(void);
esp_err_t sensors_read(sensor_reading_t *out);
