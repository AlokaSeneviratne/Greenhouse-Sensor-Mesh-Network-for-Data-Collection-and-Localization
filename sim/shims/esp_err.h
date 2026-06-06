#pragma once
#include <stdio.h>
#include <stdint.h>

typedef int esp_err_t;

#define ESP_OK                  0
#define ESP_FAIL               -1
#define ESP_ERR_INVALID_STATE   0x103
#define ESP_ERR_INVALID_ARG     0x102

static inline const char *esp_err_to_name(esp_err_t e)
{
    switch (e) {
    case ESP_OK:                return "ESP_OK";
    case ESP_FAIL:              return "ESP_FAIL";
    case ESP_ERR_INVALID_STATE: return "ESP_ERR_INVALID_STATE";
    case ESP_ERR_INVALID_ARG:   return "ESP_ERR_INVALID_ARG";
    default:                    return "ESP_ERR_UNKNOWN";
    }
}

#define ESP_ERROR_CHECK(x) \
    do { \
        esp_err_t _err = (x); \
        if (_err != ESP_OK) { \
            fprintf(stderr, "[ESP_ERROR_CHECK] %s:%d  err=%s\n", \
                    __FILE__, __LINE__, esp_err_to_name(_err)); \
        } \
    } while (0)
