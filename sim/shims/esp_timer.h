#pragma once
#include <stdint.h>
#include <time.h>

/* Returns microseconds since an arbitrary epoch (CLOCK_MONOTONIC). */
static inline uint64_t esp_timer_get_time(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}
