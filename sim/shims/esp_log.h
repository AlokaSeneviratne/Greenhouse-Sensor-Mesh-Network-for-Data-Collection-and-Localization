#pragma once
#include <stdio.h>

/* Info and warnings go to stdout so the hub's JSON lines remain parseable on
   stderr-redirected runs.  Debug/verbose are suppressed to reduce noise. */

#define ESP_LOGI(tag, fmt, ...) \
    fprintf(stderr, "[I][%s] " fmt "\n", (tag), ##__VA_ARGS__)

#define ESP_LOGW(tag, fmt, ...) \
    fprintf(stderr, "[W][%s] " fmt "\n", (tag), ##__VA_ARGS__)

#define ESP_LOGE(tag, fmt, ...) \
    fprintf(stderr, "[E][%s] " fmt "\n", (tag), ##__VA_ARGS__)

/* Suppressed in sim to keep output readable */
#define ESP_LOGD(tag, fmt, ...) do {} while (0)
#define ESP_LOGV(tag, fmt, ...) do {} while (0)
