/*
 * PhytoSense simulation host entry point.
 *
 * Reads NODE_ID and GRADIENT_LEVEL from environment variables, initialises
 * gradient_mesh.c with the real routing logic, then drives two POSIX timer
 * threads (sensor publish, gradient advertise) and a main recv loop that
 * delivers incoming UDP datagrams from the broker into gradient_mesh_on_receive.
 *
 * Usage (normally invoked by run.sh):
 *   NODE_ID=3 GRADIENT_LEVEL=2 ./sim/build/phytosense_sim
 */

#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "config.h"
#include "gradient_mesh.h"
#include "sensors.h"
#include "topology.h"
#include "transport.h"

/* ---- Globals set from env before any library call ---- */
uint8_t g_sim_node_id  = 0;   /* also read by sensors_sim.c */
static uint8_t g_sim_gradient = 0;

/* Mutex: gradient_mesh.c has no internal locking; we serialise all calls. */
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;

/* ---- Sensor publish thread ---- */

static void *sensor_thread(void *arg)
{
    (void)arg;

    /* First publish 15 s after boot, matching firmware behaviour */
    struct timespec ts = { .tv_sec = 15, .tv_nsec = 0 };
    nanosleep(&ts, NULL);

    ts.tv_sec  = SENSOR_INTERVAL_MS / 1000;
    ts.tv_nsec = (long)(SENSOR_INTERVAL_MS % 1000) * 1000000L;

    while (1) {
        sensor_reading_t r;
        pthread_mutex_lock(&g_lock);
        if (sensors_read(&r) == ESP_OK)
            gradient_mesh_publish_sensor(&r);
        pthread_mutex_unlock(&g_lock);

        nanosleep(&ts, NULL);
    }
    return NULL;
}

/* ---- Neighbour advertisement thread ---- */

static void *nbr_adv_thread(void *arg)
{
    (void)arg;

    /* Small initial stagger so not all 21 nodes flood at t=0 */
    struct timespec ts = { .tv_sec = 1, .tv_nsec = 0 };
    nanosleep(&ts, NULL);

    ts.tv_sec  = NEIGHBOR_ADV_MS / 1000;
    ts.tv_nsec = (long)(NEIGHBOR_ADV_MS % 1000) * 1000000L;

    while (1) {
        pthread_mutex_lock(&g_lock);
        gradient_mesh_advertise_level();
        pthread_mutex_unlock(&g_lock);

        nanosleep(&ts, NULL);
    }
    return NULL;
}

/* ---- Main ---- */

int main(void)
{
    /* Read identity from environment */
    const char *env_id = getenv("NODE_ID");
    const char *env_g  = getenv("GRADIENT_LEVEL");
    if (!env_id || !env_g) {
        fprintf(stderr, "Usage: NODE_ID=N GRADIENT_LEVEL=G ./phytosense_sim\n");
        return 1;
    }
    g_sim_node_id   = (uint8_t)atoi(env_id);
    g_sim_gradient  = (uint8_t)atoi(env_g);

    /*
     * The hub prints newline JSON to stdout. When stdout is redirected to a
     * file or pipe it is block-buffered by default, so a downstream reader
     * (tail -f / Get-Content -Wait / gateway.py) sees nothing until a ~4 KB
     * block fills, and lines are lost entirely if the process is killed before
     * a flush. Unbuffered output emits each reading immediately and, unlike
     * _IOLBF, is honoured on Windows too (the MSVC runtime treats _IOLBF as
     * full buffering). Hub output is one short line per reading, so the cost of
     * no buffering is negligible.
     */
    setvbuf(stdout, NULL, _IONBF, 0);

    fprintf(stderr, "[main] Node %d  gradient=%d  starting\n",
            g_sim_node_id, g_sim_gradient);

    /* Validate size assumption before any network traffic */
    _Static_assert(sizeof(sensor_data_msg_t) == 19,
                   "sensor_data_msg_t must be 19 bytes (3×uint8 + uint32 + 3×float, packed)");

    /* Transport: open send and recv UDP sockets */
    transport_init(g_sim_node_id);

    /* Sensor hardware (hub skips this) */
    if (g_sim_node_id != 0)
        sensors_init();

    /* Gradient mesh init (routing state only under HOST_SIM) */
    uint8_t dev_uuid[16] = { g_sim_node_id, 0x50, 0x68, 0x79, 0x74, 0x6f };
    gradient_mesh_init(g_sim_node_id, g_sim_gradient, dev_uuid, NULL, NULL);

    /* Mark ourselves provisioned immediately – no BLE provisioner in sim */
    uint16_t unicast = node_id_to_unicast(g_sim_node_id);
    gradient_mesh_set_provisioned(unicast);

    /* Start periodic threads */
    pthread_t t_nbr;
    pthread_create(&t_nbr, NULL, nbr_adv_thread, NULL);

    if (g_sim_node_id != 0) {
        pthread_t t_sensor;
        pthread_create(&t_sensor, NULL, sensor_thread, NULL);
    }

    /* ---- Main receive loop ---- */
    sim_hdr_t   hdr;
    uint8_t     payload[SIM_MAX_PAYLOAD];

    while (1) {
        int plen = transport_recv(&hdr, payload, sizeof(payload));
        if (plen < 0) {
            if (errno == EINTR) continue;
            perror("transport_recv");
            break;
        }

        pthread_mutex_lock(&g_lock);
        gradient_mesh_on_receive(hdr.src_addr, hdr.opcode,
                                  payload, (uint16_t)plen, hdr.rssi);
        pthread_mutex_unlock(&g_lock);
    }

    return 0;
}