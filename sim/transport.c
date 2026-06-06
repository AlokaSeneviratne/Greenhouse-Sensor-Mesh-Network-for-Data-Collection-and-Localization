#include "transport.h"
#include "esp_log.h"
#include <arpa/inet.h>
#include <endian.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define TAG "transport"

static int g_send_fd = -1;
static int g_recv_fd = -1;
static struct sockaddr_in g_broker;

void transport_init(uint8_t node_id)
{
    /* Send socket – unbound; all outbound goes to broker:BROKER_UDP_PORT */
    g_send_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_send_fd < 0) { perror("socket(send)"); return; }

    memset(&g_broker, 0, sizeof(g_broker));
    g_broker.sin_family      = AF_INET;
    g_broker.sin_port        = htons(BROKER_UDP_PORT);
    g_broker.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    /* Receive socket – bound to NODE_RECV_PORT(node_id) */
    g_recv_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_recv_fd < 0) { perror("socket(recv)"); return; }

    int reuse = 1;
    setsockopt(g_recv_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    struct sockaddr_in me = {0};
    me.sin_family      = AF_INET;
    me.sin_port        = htons((uint16_t)NODE_RECV_PORT(node_id));
    me.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (bind(g_recv_fd, (struct sockaddr *)&me, sizeof(me)) < 0) {
        perror("bind(recv)");
        return;
    }

    ESP_LOGI(TAG, "Node %d: send→broker:%d  recv←port:%d",
             node_id, BROKER_UDP_PORT, NODE_RECV_PORT(node_id));
}

esp_err_t transport_send(uint16_t src_addr, uint16_t dst_addr,
                          uint32_t opcode, const void *data, size_t len)
{
    if (g_send_fd < 0) return ESP_ERR_INVALID_STATE;
    if (len > SIM_MAX_PAYLOAD) return ESP_ERR_INVALID_ARG;

    uint8_t buf[SIM_HDR_SIZE + SIM_MAX_PAYLOAD];

    sim_hdr_t *hdr = (sim_hdr_t *)buf;
    hdr->src_addr = htole16(src_addr);
    hdr->dst_addr = htole16(dst_addr);
    hdr->opcode   = htole32(opcode);
    hdr->rssi     = 0;
    hdr->pad[0] = hdr->pad[1] = hdr->pad[2] = 0;

    memcpy(buf + SIM_HDR_SIZE, data, len);

    ssize_t sent = sendto(g_send_fd, buf, SIM_HDR_SIZE + len, 0,
                          (struct sockaddr *)&g_broker, sizeof(g_broker));
    if (sent < 0) {
        perror("sendto broker");
        return ESP_FAIL;
    }
    return ESP_OK;
}

int transport_recv(sim_hdr_t *out_hdr, uint8_t *payload, size_t payload_max)
{
    if (g_recv_fd < 0) return -1;

    uint8_t buf[SIM_HDR_SIZE + SIM_MAX_PAYLOAD];
    ssize_t n = recvfrom(g_recv_fd, buf, sizeof(buf), 0, NULL, NULL);
    if (n < (ssize_t)SIM_HDR_SIZE) return -1;

    /* Copy and byte-swap header fields to host endian */
    sim_hdr_t raw;
    memcpy(&raw, buf, SIM_HDR_SIZE);
    out_hdr->src_addr = le16toh(raw.src_addr);
    out_hdr->dst_addr = le16toh(raw.dst_addr);
    out_hdr->opcode   = le32toh(raw.opcode);
    out_hdr->rssi     = raw.rssi;    /* int8_t: no swap needed */
    memset(out_hdr->pad, 0, 3);

    size_t plen = (size_t)(n - SIM_HDR_SIZE);
    if (plen > payload_max) plen = payload_max;
    memcpy(payload, buf + SIM_HDR_SIZE, plen);
    return (int)plen;
}
