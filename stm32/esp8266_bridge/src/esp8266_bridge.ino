/*
 * esp8266_bridge.ino — ESP-01 / ESP-01S 串口 WiFi 透传桥
 *
 * 作用：把 STM32 从 UART 吐出来的字节（{"a":..,"b":..}\n，100Hz）原样搬到 TCP，
 *       PC 端 glass_overlay.py --tcp 直接读这一路，于是不再需要 USB-TTL。
 *
 * 特点：
 *   - STM32 固件一行都不用改：它的 TX 同时并到 CH340 和本模块 RX 即可
 *   - 固定 IP（路由器 DHCP 不稳也不怕），PC 端地址永远是 192.168.1.50:8266
 *   - 连不上 WiFi 时自动降级成热点 duo-glass，PC 连上后用 192.168.4.1:8266
 *   - 断线自动重连、单客户端、关 Nagle 降延迟
 *
 * 烧录见本目录 README.md（ESP-01 需要 3.3V 电平 + GPIO0 拉低才能进下载模式）
 */

#include <ESP8266WiFi.h>

/* ======================== WiFi 凭据 ========================
 * 真实凭据放 src/secrets.h（已 gitignore），模板见 src/secrets.example.h。
 * 没有 secrets.h 时用占位符编译：连不上 WiFi，芯片会自动开热点 duo-glass。
 */
#if defined(__has_include)
#  if __has_include("secrets.h")
#    include "secrets.h"
#  endif
#endif
#ifndef WIFI_SSID
#  define WIFI_SSID "your-wifi-name"
#  define WIFI_PASS "your-wifi-password"
#endif

#define USE_STATIC_IP 0                       // 手机热点网段不确定, 用 DHCP
IPAddress STATIC_IP(192, 168, 43, 50);        // USE_STATIC_IP=1 时才生效
IPAddress STATIC_GW(192, 168, 43, 1);
IPAddress STATIC_MASK(255, 255, 255, 0);

const char *AP_SSID = "duo-glass";            // 降级热点
const char *AP_PASS = "duoglass";
const uint16_t TCP_PORT = 8266;

// 1 = 关掉 WiFi 省电: 响应快(延迟 ~5ms), 电流 ~120mA
// 0 = 省电: 偶尔有 100~300ms 延迟尖峰, 电流 ~80mA
#define LOW_LATENCY 1
/* ========================================================= */

WiFiServer server(TCP_PORT);
WiFiClient client;

static void led(bool on) { digitalWrite(LED_BUILTIN, on ? LOW : HIGH); }  // ESP-01 板载灯低电平点亮

void setup()
{
    pinMode(LED_BUILTIN, OUTPUT);
    led(true);

    Serial.setRxBufferSize(1024);  // 100Hz 数据流, 默认 256B 只够 85ms, 容易溢出
    Serial.begin(115200);          // 与 STM32 一致的 115200 8N1
    Serial.setDebugOutput(false);  // 串口上只有转发数据，不能混调试信息

    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
#if LOW_LATENCY
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
#endif
#if USE_STATIC_IP
    WiFi.config(STATIC_IP, STATIC_GW, STATIC_MASK);
#endif
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    // 最多等 20 秒；失败就自己开热点，现场没有路由器也能用
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
        led((millis() / 150) % 2);
        delay(20);
    }
    if (WiFi.status() != WL_CONNECTED) {
        WiFi.mode(WIFI_AP);
        WiFi.softAP(AP_SSID, AP_PASS);
    }

    server.begin();
    server.setNoDelay(true);
    led(false);
}

void loop()
{
    // 单客户端：断了就等下一个
    if (!client || !client.connected()) {
        WiFiClient nc = server.available();
        if (nc) {
            client = nc;
            client.setNoDelay(true);
        }
    }

    // UART -> TCP
    int avail = Serial.available();
    if (avail > 0) {
        uint8_t buf[256];
        size_t want = avail > (int)sizeof(buf) ? sizeof(buf) : (size_t)avail;
        size_t n = Serial.readBytes(buf, want);
        if (n && client && client.connected()) {
            client.write(buf, n);
        }
    }

    // TCP -> UART（目前用不到，留着以后下命令）
    if (client && client.connected()) {
        while (client.available()) {
            Serial.write(client.read());
        }
    }

    // 状态灯：常亮=有客户端连上，熄灭=没连上
    static uint32_t last = 0;
    if (millis() - last > 400) {
        last = millis();
        led(client && client.connected());
    }
}