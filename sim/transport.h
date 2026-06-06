#pragma once
#include "esp_err.h"
#include <stdint.h>
#include <stddef.h>

/*
 * Wire datagram header – 12 bytes, little-endian throughout.
 * Python equivalent: struct.pack('<HHIb3x', src, dst, opcode, rssi)
 */
typedef struct __attribute__((packed)) {
    uint16_t src_addr;   /* sender's unicast mesh address            */
    uint16_t dst_addr;   /* destination unicast or 0xC000 for group  */
    uint32_t opcode;     /* 3-byte opcode encoded as uint32          */
    int8_t   rssi;       /* 0 when node sends; broker fills on relay */
    uint8_t  pad[3];
} sim_hdr_t;

_Static_assert(sizeof(sim_hdr_t) == 12, "sim_hdr_t must be 12 bytes");

#define SIM_HDR_SIZE    12
#define SIM_MAX_PAYLOAD 64   /* largest payload is sensor_data_msg_t (19 B) */

#define BROKER_UDP_PORT    7000
#define NODE_RECV_PORT(n)  (7100 + (n))   /* node N listens on 7100+N */

void      transport_init(uint8_t node_id);
esp_err_t transport_send(uint16_t src_addr, uint16_t dst_addr,
                          uint32_t opcode, const void *data, size_t len);

/* Blocking receive; returns payload byte count, fills hdr and payload buf.
   Returns -1 on socket error.  Safe to call from the main thread only. */
int transport_recv(sim_hdr_t *out_hdr, uint8_t *payload, size_t payload_max);
