#pragma once
#include <stdint.h>

/*
 * 20-node gradient mesh – PhytoSense Botanical Garden deployment
 *
 * Gradient 0 = hub ESP32 (walkway between the two buildings)
 * Gradient increases as nodes get further from the hub.
 * Each node forwards data to the closest neighbor with a lower gradient.
 *
 * Physical layout (top view, not to scale):
 *
 *   Julia greenhouse (south)              Romeo greenhouse (north)
 *   ←——————————— ~12 m ———————→ [hub] ←——————————— ~15 m ————————————→
 *
 *   g3          g2          g1      g1        g2            g3         g4
 * [18][19][20] [15][16][17] [13][14] [1][2] [3][4][5][6] [7][8][9][10] [11][12]
 *
 * Unicast address = node_id + 1  (hub = 0x0001, node 1 = 0x0002 … node 20 = 0x0015)
 */

typedef struct {
    uint8_t  node_id;
    uint8_t  gradient;
    uint16_t unicast_addr;
    char     location;   /* 'H'=hub walkway  'R'=Romeo  'J'=Julia */
    float    x_m;        /* metres east(+)/west(-) of hub          */
    float    y_m;        /* metres north(+)/south(-) of centreline */
} node_info_t;

static const node_info_t TOPOLOGY[21] = {
    /* ---- Hub ---- */
    { 0, 0, 0x0001, 'H',   0.0f,  0.0f },

    /* ---- Romeo gradient 1  (0–3 m from hub) ---- */
    { 1, 1, 0x0002, 'R',   2.5f,  1.5f },
    { 2, 1, 0x0003, 'R',   2.5f, -1.5f },

    /* ---- Romeo gradient 2  (3–7 m) ---- */
    { 3, 2, 0x0004, 'R',   5.5f,  3.0f },
    { 4, 2, 0x0005, 'R',   5.5f,  1.0f },
    { 5, 2, 0x0006, 'R',   5.5f, -1.0f },
    { 6, 2, 0x0007, 'R',   5.5f, -3.0f },

    /* ---- Romeo gradient 3  (7–11 m) ---- */
    { 7, 3, 0x0008, 'R',   9.0f,  3.5f },
    { 8, 3, 0x0009, 'R',   9.0f,  1.2f },
    { 9, 3, 0x000A, 'R',   9.0f, -1.2f },
    {10, 3, 0x000B, 'R',   9.0f, -3.5f },

    /* ---- Romeo gradient 4  (11–15 m, far apex) ---- */
    {11, 4, 0x000C, 'R',  13.0f,  1.5f },
    {12, 4, 0x000D, 'R',  13.0f, -1.5f },

    /* ---- Julia gradient 1  (0–3 m from hub) ---- */
    {13, 1, 0x000E, 'J',  -2.5f,  1.5f },
    {14, 1, 0x000F, 'J',  -2.5f, -1.5f },

    /* ---- Julia gradient 2  (3–7 m) ---- */
    {15, 2, 0x0010, 'J',  -5.5f,  2.5f },
    {16, 2, 0x0011, 'J',  -5.5f,  0.0f },
    {17, 2, 0x0012, 'J',  -5.5f, -2.5f },

    /* ---- Julia gradient 3  (7–12 m, far apex) ---- */
    {18, 3, 0x0013, 'J',  -9.0f,  2.0f },
    {19, 3, 0x0014, 'J',  -9.0f,  0.0f },
    {20, 3, 0x0015, 'J',  -9.0f, -2.0f },
};

static inline uint16_t node_id_to_unicast(uint8_t nid)  { return (uint16_t)(nid + 1); }
static inline uint8_t  unicast_to_node_id(uint16_t addr) { return (uint8_t)(addr - 1); }
