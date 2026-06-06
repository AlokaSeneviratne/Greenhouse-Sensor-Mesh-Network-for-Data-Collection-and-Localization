/*
 * Synthetic sensor implementation for HOST_SIM.
 * Replaces sensors.c entirely – same API, no hardware.
 *
 * Values are derived from the node's physical position in topology.h:
 *   Romeo (R): warm-humid tropical base  (26 °C / 72 % RH / 55 % soil)
 *   Julia (J): cool-dry mediterranean    (21 °C / 60 % RH / 40 % soil)
 *
 * A slow sine drift (~4 h period) and small per-reading noise are added so
 * the viewer shows plausible live variation rather than frozen values.
 */

#include "sensors.h"
#include "topology.h"
#include "esp_log.h"
#include <math.h>
#include <time.h>
#include <string.h>

#define TAG "sensors_sim"

/* Defined in node_main.c; sensors_sim.c reads it to look up TOPOLOGY position. */
extern uint8_t g_sim_node_id;

static bool s_init = false;

esp_err_t sensors_init(void)
{
    s_init = true;
    ESP_LOGI(TAG, "Sim sensors ready (node %d)", g_sim_node_id);
    return ESP_OK;
}

esp_err_t sensors_read(sensor_reading_t *out)
{
    if (!s_init || !out) return ESP_ERR_INVALID_STATE;

    /* Look up this node's position */
    const node_info_t *info = NULL;
    for (int i = 0; i < 21; i++) {
        if (TOPOLOGY[i].node_id == g_sim_node_id) { info = &TOPOLOGY[i]; break; }
    }
    if (!info) return ESP_ERR_INVALID_STATE;

    /* Monotonic time for drift and timestamp */
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    double t_sec = (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;

    /* Base values per greenhouse */
    float base_t, base_h, base_s;
    if (info->location == 'R') {
        base_t = 26.0f; base_h = 72.0f; base_s = 55.0f;
    } else {
        base_t = 21.0f; base_h = 60.0f; base_s = 40.0f;
    }

    /* Gradient-distance modifier: deeper = slightly cooler, more humid */
    float dist = sqrtf(info->x_m * info->x_m + info->y_m * info->y_m);
    base_t -= 0.25f * dist / 5.0f;
    base_h += 2.0f  * dist / 9.0f;

    /* Slow sine drift (±1.5 °C, ±3 % RH) over a 4-hour period */
    float drift = (float)sin(2.0 * M_PI * t_sec / (4.0 * 3600.0));
    base_t += 1.5f * drift;
    base_h += 3.0f * drift;

    /* Deterministic per-second noise seeded by node_id so each node differs */
    uint32_t seed = (uint32_t)ts.tv_sec ^ ((uint32_t)g_sim_node_id * 2654435761u);
    /* LCG three rounds to get independent noise for each channel */
    seed = seed * 1664525u + 1013904223u;
    float noise_t = ((float)(int8_t)(seed & 0xFF)) * (0.3f / 128.0f);
    seed = seed * 1664525u + 1013904223u;
    float noise_h = ((float)(int8_t)(seed & 0xFF)) * (1.0f / 128.0f);
    seed = seed * 1664525u + 1013904223u;
    float noise_s = ((float)(int8_t)(seed & 0xFF)) * (2.0f / 128.0f);

    out->temperature_c     = base_t + noise_t;
    out->humidity_pct      = base_h + noise_h;
    out->soil_moisture_pct = base_s + noise_s;

    /* Clamp */
    if (out->humidity_pct      < 0.0f)   out->humidity_pct      = 0.0f;
    if (out->humidity_pct      > 100.0f) out->humidity_pct      = 100.0f;
    if (out->soil_moisture_pct < 0.0f)   out->soil_moisture_pct = 0.0f;
    if (out->soil_moisture_pct > 100.0f) out->soil_moisture_pct = 100.0f;

    out->timestamp_s = (uint32_t)ts.tv_sec;
    return ESP_OK;
}
