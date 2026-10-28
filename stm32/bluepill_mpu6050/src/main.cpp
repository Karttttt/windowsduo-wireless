/*
 * mpu6050_angle_main.cpp  —  STM32F103C8T6 (Blue Pill) 移植版 v1
 *
 * iPhone Duo「悬浮玻璃」效果 - 角度读取固件
 * 移植自 esp32/mpu6050_angle/main/mpu6050_angle_main.c (ESP-IDF v5.x)
 * 算法、滤波参数、串口协议与输出格式完全一致，只替换了平台层:
 *   ESP-IDF esp_timer / i2c_master  ->  Arduino millis()/micros() + Wire (I2C1)
 *   ESP_LOGI / printf               ->  Serial (USART1)
 *
 * 启动流程（串口可见）:
 *   1. I2C 初始化 + WHO_AM_I 校验
 *   2. 陀螺仪零漂校准: 3 秒采样, 静止检测, 失败自动重试
 *   3. 100Hz 角度输出 (互补滤波, 陀螺仪零漂已扣除)
 *
 * 串口输出: USART1 / 115200, JSON 行 {"a":主角度,"b":副轴角度}
 *   a = 主轴角度 (HINGE_AXIS 决定, 默认绕 Y 轴)
 *   b = 另一轴的角度 (调试用: 判断模块安装方向)
 *
 * 接线:
 *   MPU6050 VCC -> Blue Pill 5V (GY-521 带 LDO; 裸芯片请接 3.3V)
 *   MPU6050 GND -> GND
 *   MPU6050 SCL -> PB6      MPU6050 SDA -> PB7      AD0 -> GND (地址 0x68)
 *   CH340 TX    -> PA10(RX) CH340 RX     -> PA9(TX)  GND 共地
 *   ST-Link SWDIO->PA13     SWCLK->PA14  3.3V/GND 供电
 *
 * 装贴建议: 让模块的 Y 轴(丝印 Y 方向)平行于笔记本转轴。
 * 如果掰动模块时 a 不变而 b 变 → 把 HINGE_AXIS 改为 AXIS_X 重新烧录，
 * 或者干脆在 PC 端 win/config.json 里把 "axis" 改成 "b"（无需重烧）。
 */

#include <Arduino.h>
#include <Wire.h>
#include <math.h>

static const char *TAG = "mpu6050";

/* ---------------- 配置 ---------------- */
/* Blue Pill: I2C1 默认引脚 PB6=SCL, PB7=SDA (与 GY-521 直连) */
#define I2C_SDA_PIN     PB7
#define I2C_SCL_PIN     PB6
#define I2C_FREQ_HZ     400000
#define MPU_ADDR        0x68        // AD0 悬空/GND = 0x68

#define SAMPLE_HZ       100
#define SAMPLE_DT       (1.0f / SAMPLE_HZ)

/*
 * 铰链轴选择:
 *   AXIS_Y(默认): 模块 Y 轴平行于转轴, 角度 = 绕 Y 轴旋转
 *   AXIS_X      : 模块 X 轴平行于转轴, 角度 = 绕 X 轴旋转
 * 方向: 若"开盖时角度变小", 把 HINGE_SIGN 改为 -1
 */
#define AXIS_Y          0
#define AXIS_X          1
#define HINGE_AXIS      AXIS_Y
#define HINGE_SIGN      1

#define CF_GYRO         0.98f
#define CF_ACC          0.02f
#define OUT_ALPHA       0.3f
#define ACC_LP_ALPHA    0.2f        // 加速度计角度低通
/* -------------------------------------- */

/* MPU6050 寄存器 */
#define REG_SMPLRT_DIV  0x19
#define REG_CONFIG      0x1A
#define REG_GYRO_CFG    0x1B
#define REG_ACCEL_CFG   0x1C
#define REG_PWR_MGMT1   0x6B
#define REG_WHO_AM_I    0x75
#define REG_ACCEL_XOUT  0x3B

typedef struct {
    float ax, ay, az;   // g
    float gx, gy, gz;   // deg/s (原始, 未扣零漂)
} imu_sample_t;

/* ---------------- I2C 平台层 ---------------- */
static bool mpu_write(uint8_t reg, uint8_t val)
{
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission(true) == 0;
}

static bool mpu_read(uint8_t reg, uint8_t *data, uint8_t len)
{
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((int)MPU_ADDR, (int)len) != len) return false;
    for (uint8_t i = 0; i < len; i++) data[i] = (uint8_t)Wire.read();
    return true;
}

static bool mpu_read_sample(imu_sample_t *s)
{
    uint8_t d[14];
    if (!mpu_read(REG_ACCEL_XOUT, d, 14)) return false;
    s->ax = (int16_t)((d[0] << 8) | d[1]) / 16384.0f;   // ±2g
    s->ay = (int16_t)((d[2] << 8) | d[3]) / 16384.0f;
    s->az = (int16_t)((d[4] << 8) | d[5]) / 16384.0f;
    s->gx = (int16_t)((d[8] << 8) | d[9]) / 131.0f;     // ±250dps
    s->gy = (int16_t)((d[10] << 8) | d[11]) / 131.0f;
    s->gz = (int16_t)((d[12] << 8) | d[13]) / 131.0f;
    return true;
}

static bool mpu_init(void)
{
    uint8_t who = 0;
    if (!mpu_read(REG_WHO_AM_I, &who, 1)) return false;
    Serial.print("[");
    Serial.print(TAG);
    Serial.print("] WHO_AM_I = 0x");
    Serial.println(who, HEX);
    if (who != 0x68) return false;

    if (!mpu_write(REG_PWR_MGMT1, 0x00)) return false;   // wake
    delay(50);
    if (!mpu_write(REG_SMPLRT_DIV, 0x00)) return false;
    if (!mpu_write(REG_CONFIG, 0x03)) return false;       // DLPF 44Hz
    if (!mpu_write(REG_GYRO_CFG, 0x00)) return false;     // ±250dps
    if (!mpu_write(REG_ACCEL_CFG, 0x00)) return false;    // ±2g
    if (!mpu_read(REG_PWR_MGMT1, &who, 1)) return false;  // 回读确认
    if (who != 0x00) return false;
    return true;
}

/* 加速度计角度: 绕 Y 轴 (AXIS_Y) 或绕 X 轴 (AXIS_X) */
static inline float acc_angle_axis(const imu_sample_t *s, int axis)
{
    if (axis == AXIS_Y)
        return atan2f(-s->ax, sqrtf(s->ay * s->ay + s->az * s->az)) * 57.29578f;
    else
        return atan2f(s->ay, sqrtf(s->ax * s->ax + s->az * s->az)) * 57.29578f;
}

static inline float gyro_axis(const imu_sample_t *s, int axis)
{
    return (axis == AXIS_Y) ? s->gy : s->gx;
}

/* ---------- 陀螺仪零漂校准: 3s 采样 + 静止检测, 失败重试 ---------- */
static void gyro_calibrate(float *off_gx, float *off_gy, float *off_gz)
{
    const int N = 300;                       // 3s @ 100Hz
    for (;;) {
        Serial.print("[");
        Serial.print(TAG);
        Serial.println("] >>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<");
        float sx = 0, sy = 0, sz = 0;
        float amag_min = 1e9f, amag_max = -1e9f;
        imu_sample_t s;
        bool ok = true;

        for (int i = 0; i < N; i++) {
            if (!mpu_read_sample(&s)) {
                Serial.print("[");
                Serial.print(TAG);
                Serial.println("] 校准期间 I2C 读取失败, 重试");
                ok = false;
                break;
            }
            sx += s.gx; sy += s.gy; sz += s.gz;
            float amag = sqrtf(s.ax * s.ax + s.ay * s.ay + s.az * s.az);
            if (amag < amag_min) amag_min = amag;
            if (amag > amag_max) amag_max = amag;
            delay(1000 / SAMPLE_HZ);
        }
        if (!ok) { delay(500); continue; }

        /* 静止检测: 加速度模长波动应 < 0.05g */
        if (amag_max - amag_min > 0.05f) {
            Serial.print("[");
            Serial.print(TAG);
            Serial.print("] 检测到晃动(幅值波动 ");
            Serial.print(amag_max - amag_min, 3);
            Serial.println("g), 重新校准...");
            continue;
        }
        *off_gx = sx / N; *off_gy = sy / N; *off_gz = sz / N;
        Serial.print("[");
        Serial.print(TAG);
        Serial.print("] 校准完成! 零漂偏移: gx=");
        Serial.print(*off_gx, 2);
        Serial.print(" gy=");
        Serial.print(*off_gy, 2);
        Serial.print(" gz=");
        Serial.print(*off_gz, 2);
        Serial.println(" (deg/s)");
        return;
    }
}

/* ---------------- 浮点定宽输出 (避免 newlib printf %f) ---------------- */
static int fmt2(char *out, float v)
{
    bool neg = (v < 0.0f);
    long m = lroundf(fabsf(v) * 100.0f);
    long ip = m / 100;
    long fp = m % 100;
    return neg ? sprintf(out, "-%ld.%02ld", ip, fp)
               : sprintf(out, "%ld.%02ld", ip, fp);
}

/* 守恒的状态量 */
static float angle = 0, acc_f = 0, out_f = 0;
static float off_gx = 0, off_gy = 0, off_gz = 0;

void setup()
{
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.print("[");
    Serial.print(TAG);
    Serial.println("] STM32F103C8T6 / USART1 115200 / I2C1 PB6(SCL) PB7(SDA)");
    Serial.print("[");
    Serial.print(TAG);
    Serial.println("] 编译时间: " __DATE__ " " __TIME__);

    Wire.setSDA(I2C_SDA_PIN);
    Wire.setSCL(I2C_SCL_PIN);
    Wire.begin();
    Wire.setClock(I2C_FREQ_HZ);

    /* 1. 传感器初始化 (未接线时每 2s 重试, 不崩溃) */
    while (!mpu_init()) {
        Serial.print("[");
        Serial.print(TAG);
        Serial.println("] MPU6050 未就绪。检查接线: VCC->5V GND->GND "
                       "SCL->PB6 SDA->PB7 AD0->GND，2 秒后重试...");
        delay(2000);
    }
    Serial.print("[");
    Serial.print(TAG);
    Serial.println("] MPU6050 初始化 OK");

    /* 2. 陀螺仪零漂校准 */
    gyro_calibrate(&off_gx, &off_gy, &off_gz);

    /* 3. 首帧用加速度计对齐, 避免互补滤波从 0 慢慢收敛 */
    imu_sample_t s0;
    if (mpu_read_sample(&s0)) {
        angle = acc_f = out_f = acc_angle_axis(&s0, HINGE_AXIS) * HINGE_SIGN;
    }

    Serial.print("[");
    Serial.print(TAG);
    Serial.println("] 开始输出角度 @" "100" "Hz: {\"a\":主角度,\"b\":副轴角度}");
}

void loop()
{
    static uint32_t next_us = 0;
    if (next_us == 0) next_us = micros();

    imu_sample_t s;
    if (mpu_read_sample(&s)) {
        float main_acc = acc_angle_axis(&s, HINGE_AXIS) * HINGE_SIGN;
        float main_gyro = gyro_axis(&s, HINGE_AXIS) * HINGE_SIGN;

        /* 扣除零漂 */
        float g = main_gyro - ((HINGE_AXIS == AXIS_Y) ? off_gy : off_gx) * HINGE_SIGN;

        acc_f += ACC_LP_ALPHA * (main_acc - acc_f);

        angle = CF_GYRO * (angle + g * SAMPLE_DT) + CF_ACC * acc_f;
        if (fabsf(angle - acc_f) > 45.0f) angle = acc_f;   // 发散保护
        out_f += OUT_ALPHA * (angle - out_f);

        /* b = 另一轴角度, 用于判断安装方向 */
        float other = acc_angle_axis(&s, (HINGE_AXIS == AXIS_Y) ? AXIS_X : AXIS_Y);

        char line[64];
        int n = 0;
        n += sprintf(line + n, "{\"a\":");
        n += fmt2(line + n, out_f);
        n += sprintf(line + n, ",\"b\":");
        n += fmt2(line + n, other);
        line[n++] = '}';
        line[n++] = '\n';
        Serial.write((const uint8_t *)line, n);
    } else {
        Serial.print("[");
        Serial.print(TAG);
        Serial.println("] I2C 读取失败, 检查接线");
        delay(100);
    }

    next_us += 1000000UL / SAMPLE_HZ;
    int32_t wait = (int32_t)(next_us - micros());
    if (wait > 0) {
        delayMicroseconds((uint32_t)wait);
    } else {
        next_us = micros();          // 落后太多则重同步, 不补帧
    }
}