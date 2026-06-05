#include "sensors.h"
#include "config.h"
#include "esp_log.h"
#include "driver/i2c.h"
#include "driver/adc.h"
#include "esp_adc_cal.h"
#include "esp_timer.h"
#include <math.h>

#define TAG "sensors"

/* SHT31-D single-shot measurement (clock-stretch, high repeatability) */
#define SHT31_CMD_MEAS  0x2C06
#define SHT31_CMD_RESET 0x30A2

static esp_adc_cal_characteristics_t s_adc_chars;
static bool s_init = false;

/* ---- SHT31-D I2C helpers ---- */

static esp_err_t sht31_write(uint16_t cmd)
{
    uint8_t buf[2] = { cmd >> 8, cmd & 0xFF };
    i2c_cmd_handle_t h = i2c_cmd_link_create();
    i2c_master_start(h);
    i2c_master_write_byte(h, (SHT31_I2C_ADDR << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write(h, buf, 2, true);
    i2c_master_stop(h);
    esp_err_t ret = i2c_master_cmd_begin(I2C_PORT, h, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(h);
    return ret;
}

static esp_err_t sht31_read(uint16_t *raw_t, uint16_t *raw_h)
{
    uint8_t d[6] = {0};
    i2c_cmd_handle_t h = i2c_cmd_link_create();
    i2c_master_start(h);
    i2c_master_write_byte(h, (SHT31_I2C_ADDR << 1) | I2C_MASTER_READ, true);
    i2c_master_read(h, d, 6, I2C_MASTER_LAST_NACK);
    i2c_master_stop(h);
    esp_err_t ret = i2c_master_cmd_begin(I2C_PORT, h, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(h);
    if (ret != ESP_OK) return ret;
    /* bytes: [0][1] temp MSB/LSB, [2] CRC, [3][4] hum MSB/LSB, [5] CRC */
    *raw_t = (uint16_t)((d[0] << 8) | d[1]);
    *raw_h = (uint16_t)((d[3] << 8) | d[4]);
    return ESP_OK;
}

/* ---- Public API ---- */

esp_err_t sensors_init(void)
{
    i2c_config_t cfg = {
        .mode             = I2C_MODE_MASTER,
        .sda_io_num       = SHT31_SDA_PIN,
        .scl_io_num       = SHT31_SCL_PIN,
        .sda_pullup_en    = GPIO_PULLUP_ENABLE,
        .scl_pullup_en    = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_FREQ_HZ,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_PORT, &cfg));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_PORT, I2C_MODE_MASTER, 0, 0, 0));

    esp_err_t ret = sht31_write(SHT31_CMD_RESET);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "SHT31 reset failed: %s", esp_err_to_name(ret));
        return ret;
    }
    vTaskDelay(pdMS_TO_TICKS(15));

    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(SOIL_ADC_CHANNEL, SOIL_ADC_ATTEN);
    esp_adc_cal_characterize(ADC_UNIT_1, SOIL_ADC_ATTEN, ADC_WIDTH_BIT_12,
                              1100, &s_adc_chars);

    s_init = true;
    ESP_LOGI(TAG, "Sensors ready");
    return ESP_OK;
}

esp_err_t sensors_read(sensor_reading_t *out)
{
    if (!s_init || !out) return ESP_ERR_INVALID_STATE;

    /* Trigger SHT31 measurement and wait for conversion (<15 ms) */
    esp_err_t ret = sht31_write(SHT31_CMD_MEAS);
    if (ret != ESP_OK) return ret;
    vTaskDelay(pdMS_TO_TICKS(20));

    uint16_t raw_t, raw_h;
    ret = sht31_read(&raw_t, &raw_h);
    if (ret != ESP_OK) return ret;

    out->temperature_c  = -45.0f + 175.0f * (float)raw_t / 65535.0f;
    out->humidity_pct   = 100.0f * (float)raw_h / 65535.0f;

    /* Average 16 ADC samples to reduce noise */
    uint32_t sum = 0;
    for (int i = 0; i < 16; i++) sum += adc1_get_raw(SOIL_ADC_CHANNEL);
    int raw_soil = (int)(sum / 16);
    float pct = 100.0f * (float)(SOIL_DRY_RAW - raw_soil)
                       / (float)(SOIL_DRY_RAW - SOIL_WET_RAW);
    out->soil_moisture_pct = fmaxf(0.0f, fminf(100.0f, pct));

    out->timestamp_s = (uint32_t)(esp_timer_get_time() / 1000000ULL);

    ESP_LOGD(TAG, "T=%.1f H=%.1f S=%.1f", out->temperature_c,
             out->humidity_pct, out->soil_moisture_pct);
    return ESP_OK;
}
