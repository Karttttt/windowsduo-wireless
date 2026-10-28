# ESP8266 串口 WiFi 透传桥

把 STM32 的串口角度流搬到 TCP，PC 端就能**不插 USB-TTL** 收数据，配合电池可以整机无线。

```
GY-521 ──I2C── Blue Pill ──USART1 TX (PA9)──┬── CH340 RX   (可选，调试用)
                                            └── ESP8266 RX ──WiFi/TCP──> PC (run_wifi.bat)
```

STM32 的 TX 是普通 UART 输出，**并给两个接收端不会互相影响**（都是高阻输入），
所以 `stm32/bluepill_mpu6050` 的固件**一行都不用改**。

---

## 0. 用你手上这块（NodeMCU / ESP-12E + CH340 + Type-C）

三步：

1. **烧固件**：改 `src/esp8266_bridge.ino` 顶部 WiFi 名/密码 → 板子 USB 插电脑 → `flash.bat COMx`
2. **接线**：STM32 `PA9` → NodeMCU **RX**，GND 共地；电源模块 5V → **VIN**
3. **跑**：`WindowsDuo\win\run_wifi.bat`

板载 CH340 只在烧录时用；正常无线运行时**不要插这块板的 USB**（见第 4 节说明）。

## 1. 为什么不用自带的 AT 固件

AT 固件能做透传，但透明模式要求「客户端连上后手动发一次 `AT+CIPSEND`」，
而且 **WiFi 断开 / PC 重连后必须重新进一次透明模式** —— 需要一个"人"或"另一个 MCU"盯着发命令。

本目录是一个 60 行的 Arduino 固件：开机连 WiFi、开 TCP 服务、串口↔TCP 无脑转发、
断线自愈、状态灯自解释。刷一次，以后不用管。

## 2. 接线

### A. NodeMCU / 物联网开发板（ESP-12E，推荐）

| NodeMCU | 接到 | 说明 |
|---|---|---|
| **RX**（GPIO3） | **STM32 PA9 (TX)** | 只接这一根数据线 |
| TX | 不接 | 只回传数据用不上；留着以后能下发命令 |
| GND | GND | 必须共地 |
| **VIN** | 5V | 电池/电源模块 ≥1A，板载 AMS1117 转 3.3V |
| （3V3） | — | 不要和 VIN 同时送电；只有外部已是稳压 3.3V 时才用这脚 |

> NodeMCU 板上 CH340 的 TX 通过 ~470Ω 电阻也连在同一个 RX 节点上。
> 没插 USB 时它输出高电平，靠这颗电阻限流，实践上不影响 STM32 驱动这根线；
> 但**烧录时请先把 STM32 断电或拔掉 PA9 那根线**，避免两个发送端互相干扰。

### B. ESP-01 / ESP-01S（8 脚小模块，需要独立 3.3V）

| ESP-01 | 接到 | 说明 |
|---|---|---|
| VCC | **3.3V** | 绝对不要接 5V；必须独立 LDO |
| GND | GND | 共地 |
| RXD | STM32 PA9 (TX) | 与 CH340 的 RXD 并联 |
| TXD | 不接 / PA10 | 可选 |
| CH_PD (EN) | 3.3V | 悬空会随机重启（10kΩ 更稳） |
| GPIO0 | 3.3V | **运行时必须高**，烧录时才拉低 |
| GPIO2 | 3.3V 或悬空 | 上电需高电平，模块板载一般已上拉 |

## 3. 供电（决定能不能真的无线）

| 器件 | 平均电流 | 峰值 |
|---|---|---|
| NodeMCU（WiFi 常连 + 持续发流） | ~80 mA | ~350 mA |
| Blue Pill + GY-521 | ~45 mA | ~50 mA |
| **合计** | **~125 mA** | ~400 mA |

- 2000mAh 的电池大约 **13~15 小时**；5000mAh 约 35 小时
- 电源模块要能稳定给 **5V / ≥1A**（峰值余量很重要，否则 WiFi 一发包就重启）
- 两个板子**必须共地**
- ESP-01 那种没有 LDO 的模块，再加一级 AMS1117-3.3 + 470µF 电解 + 100nF 陶瓷

## 4. 烧录

### NodeMCU（你这款）

板载 CH340 + 自动下载电路，**不需要动 GPIO0**：

```bat
flash.bat COM5              :: 默认 nodemcu 环境
flash.bat COM5 esp01        :: 如果你要烧 ESP-01
```

烧完拔掉 USB 即可；正常无线运行时不要插这块板的 USB（避免 CH340 和 STM32 抢同一条 RX）。

### ESP-01（需要 3.3V TTL）

1. 接 3.3V USB-TTL：`TXD→RXD`、`RXD→TXD`、`GND`、`VCC→3.3V`，`CH_PD→3.3V`
2. **GPIO0 接 GND**，然后断开再上电
3. `flash.bat COMx esp01`
4. 烧完 GPIO0 接回 3.3V（或悬空），再上电

> 首次编译会下载 `espressif8266` 平台和工具链（约 250MB），本项目已装好。
> 两个 bat 会自动建 `C:\duo` 联接并把 `TMP` 指到 `C:\duo\Temp`，
> 否则中文路径 + 系统临时目录会让工具链报错。

## 5. 配置

WiFi 凭据**不写在 .ino 里**，放 `src/secrets.h`（已 gitignore）。第一次使用：

```bat
copy src\secrets.example.h src\secrets.h
```

然后编辑 `src/secrets.h`：

```cpp
#define WIFI_SSID "你的热点名"
#define WIFI_PASS "你的密码"
```

其余可调项留在 `src/esp8266_bridge.ino` 顶部：

```cpp
#define USE_STATIC_IP 0                   // 0 = DHCP（推荐）
```

**推荐用 DHCP + PC 端自动发现**：手机热点/路由器的网段和租约都不固定，写死 IP 反而容易连不上。
程序启动时会在当前 /24 里扫 8266 端口，1~2 秒就能找到桥（`scan_for_bridge()`）。

想固定 IP 就把 `USE_STATIC_IP` 改成 1，并填上 `STATIC_IP` / `STATIC_GW` / `STATIC_MASK`
（注意网关要和你实际网段一致）。

**连不上 WiFi 会自动开热点** `duo-glass`（密码 `duoglass`），
PC 连这个热点后 `run_wifi.bat 192.168.4.1:8266`（此时电脑没有外网）。

## 6. PC 端用法

```bat
WindowsDuo\win\run_wifi.bat                        :: 自动发现（推荐）
WindowsDuo\win\run_wifi.bat 10.234.186.114:8266    :: 已知地址时直接指定
WindowsDuo\win\run_wifi.bat --duration=30          :: 演示：30 秒后自动退出
```

忘了地址也能找回来：

```bat
.venv\Scripts\python.exe WindowsDuo\stm32\esp8266_bridge\find_ip.py
```

状态栏显示 `[tcp 10.234.186.114:8266 100Hz]`。

- 与串口模式**接口完全一致**：按键、标定、渲染都不变
- 断线后每 2 秒自动重连；`auto` 模式每次重连都会重新扫描
- 两套可以共存：`run_overlay.bat` 走串口，`run_wifi.bat` 走网络

### 日常使用流程

1. 手机开热点（**必须是 2.4GHz**，安卓选 2.4G，iPhone 开"最大兼容性"）
2. ESP 和 STM32 上电（ESP 约 3 秒连上）
3. 笔记本连这个热点
4. 双击 `run_wifi.bat`

## 7. 实测

| 项 | 数值 |
|---|---|
| 数据量 | ~30 B/帧 × 100Hz ≈ 3 KB/s |
| 链路延迟 | 局域网一般 5~30ms（已开 TCP_NODELAY） |
| 实测吞吐 | ESP→PC 799 帧/8s（≈100Hz 无丢帧） |
| PC 端解析 | 假服务器 1017 帧/10.2s，客户端稳定显示 100Hz |
| 固件体积 | NodeMCU: Flash 36.6% / RAM 34.6% |

## 8. 常见问题

| 现象 | 原因 |
|---|---|
| 连不上、灯一直闪 | WiFi 名/密码错；或供电不足（换 ≥1A 电源 + 加大电容） |
| 能连路由但 PC 连不上 TCP | 固定 IP 与网段不匹配；PC 和 ESP 不在同一网段 |
| 连上几秒就断 | 供电跌落；检查 VIN 电压与电容 |
| 数据乱码 | 波特率必须是 115200（STM32 与本固件一致） |
| 烧录失败 | NodeMCU 换根好数据线；ESP-01 确认 GPIO0 已拉低 |
| 想确认 ESP 在线 | 状态灯长亮=有客户端；或 `ping 192.168.1.50` |

## 9. 值得不值得

- **值得**：传感器+主控+ESP 整体贴在屏幕背盖，转轴处一根线都不用穿；配电池真正无线
- **代价**：多一块板、多一份耗电、多一次刷机、PC 要连同一局域网
- **建议**：先保留有线（`run_overlay.bat`）当调试通路，无线跑通后再拔线