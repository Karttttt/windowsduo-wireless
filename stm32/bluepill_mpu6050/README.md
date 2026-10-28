# STM32F103C8T6 (Blue Pill) + MPU6050 角度读取固件

ESP-IDF 版固件 (`esp32/mpu6050_angle/`) 的 **STM32 移植**。算法、互补滤波参数、
陀螺仪零漂校准、串口 JSON 协议与 ESP32 版完全一致，只替换了平台层：

| 平台层 | ESP32 原版 | STM32 本版 |
|---|---|---|
| I2C | `driver/i2c_master.h` (GPIO22/23) | Arduino `Wire` (I2C1: PB6/PB7) |
| 定时 | FreeRTOS `vTaskDelayUntil` | `micros()` 绝对时基 |
| 串口 | ESP-IDF `printf` / USB-UART | `Serial` (USART1: PA9/PA10) |
| 构建 | ESP-IDF v5.4 | PlatformIO + Arduino core (ststm32) |

串口输出：`USART1 @ 115200`，100Hz，格式 `{"a":主轴角,"b":副轴角}` —— PC 端
`win/glass_overlay.py` 无需任何修改即可识别。

---

## 1. 硬件清单

| 件 | 说明 |
|---|---|
| STM32F103C8T6 最小系统板 | 俗称 Blue Pill，64KB Flash / 20KB RAM |
| GY-521（MPU6050） | 6 轴陀螺仪加速度计，I2C 地址 0x68 |
| ST-Link V2 | 烧录用（SWD 四线） |
| CH340 / CP2102 USB-TTL | 角度数据回传给电脑 |
| 杜邦线、3M 双面胶 | 走线 + 固定模块 |

## 2. 接线

### MPU6050 → Blue Pill

| GY-521 | Blue Pill | 说明 |
|---|---|---|
| VCC | **5V** | GY-521 板载 LDO，接 5V 最稳；裸芯片请接 3.3V |
| GND | GND | |
| SCL | **PB6** | I2C1 SCL |
| SDA | **PB7** | I2C1 SDA |
| AD0 | GND | 决定地址 0x68；接 3.3V 则变成 0x69（固件要改 `MPU_ADDR`） |
| XDA / XCL / INT | 不接 | |

> Blue Pill 板上 PB6/PB7 没有上拉，GY-521 模块自带 4.7kΩ 上拉，直连即可。

### USB-TTL → Blue Pill（角度回传）

| CH340 | Blue Pill |
|---|---|
| TX | **PA10** (USART1 RX) |
| RX | **PA9** (USART1 TX) |
| GND | GND |

### ST-Link V2 → Blue Pill（烧录）

| ST-Link | Blue Pill |
|---|---|
| SWDIO | PA13 |
| SWCLK | PA14 |
| GND | GND |
| 3.3V | 3.3V（给板子供电） |

> 烧录时若 CH340 的 TX 也接着 PA10，一般不影响 SWD；不放心可只留 ST-Link 三根线。

## 3. 编译与烧录

工程目录：`stm32/bluepill_mpu6050/`，用 PlatformIO 构建。**双击 bat 即可**：

```bat
build.bat    :: 编译  -> .pio\build\bluepill\firmware.bin
flash.bat    :: ST-Link 烧录
```

bat 里做了两件本机必须的事（否则工具链会报错）：

1. 用目录联接 `C:\duo` 指向本目录 —— arm-none-eabi 链接器打不开中文路径下的 `ldscript.ld`；
2. 把 `TMP`/`TEMP` 指到 `C:\duo\Temp` —— 指向 `C:\Temp` 会 `Permission denied`。

首次编译已由本项目完成，`.platformio/`（约 2.6GB 工具链）已就位，**不需要再联网**。

**没有 ST-Link / OpenOCD 打不开设备时**，用串口 ISP 烧录（免驱动、最省事）：

1. BOOT0 跳线帽拨到 **1**，按一下复位键
2. `platformio run -e bluepill_isp -t upload --upload-port COMx`
3. 烧完把 BOOT0 拨回 **0**，再复位

编译产物：`.pio/build/bluepill/firmware.bin`（可留档，重烧不必再联网）。

## 4. 验证角度输出

```powershell
# 在仓库根目录（duo\）执行；.venv 已装好 pyserial
.venv\Scripts\python.exe WindowsDuo\esp32\debug_view.py --port COM9
```

正常表现：

```
[mpu6050] WHO_AM_I = 0x68
[mpu6050] MPU6050 初始化 OK
[mpu6050] >>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<
[mpu6050] 校准完成! 零漂偏移: gx=... gy=... gz=... (deg/s)
[mpu6050] 开始输出角度 @100Hz
a  42.15° [#######.....] 半开     | 副轴b   3.21° |  99.8Hz 帧:1234 ...
```

## 5. 装到笔记本上

1. **模块固定**：GY-521 用 3M 胶平贴在屏幕**背盖内侧**（芯片正面朝外），
   让模块丝印的 **Y 轴与笔记本转轴平行**（这是默认 `HINGE_AXIS = AXIS_Y` 的约定）。
2. **走线**：USB 线从转轴缝隙引到机身/桌面，别绷太紧，转轴处留一段余量。
3. **不要挡住磁铁/霍尔传感器**：笔记本盖上会休眠，本项目靠 `lock_at_close` 决定是否锁屏，
   如果笔记本自己合盖就休眠，把电源设置里「关闭盖子时」改成「不采取任何操作」。

## 6. 标定（关键一步）

固件输出的是**相对重力的原始 pitch**，不等于几何开合角，所以要读两个极值写进 PC 端配置：

```powershell
# 在仓库根目录执行（也可直接双击 WindowsDuo\win\run_calibrate.bat）
.venv\Scripts\python.exe WindowsDuo\win\calibrate.py
```

按提示：合盖 → 回车；开到最大 → 回车。脚本会打印并可选写回 `win/config.json` 的
`angle_closed` / `angle_open`。

如果 `a` 几乎不变而 `b` 在变，说明模块贴的方向绕错了轴：

- 免重烧：`config.json` 里把 `"axis"` 改成 `"b"`
- 或改固件 `HINGE_AXIS` 为 `AXIS_X` 后重烧

开盖角度变小/变大方向反了也不用重烧：标定脚本会按实测值填 `angle_closed`/`angle_open`，
顺序天然正确。

## 7. 与 ESP32 原版的差异 / 已知点

- `SAMPLE_HZ=100`、`CF_GYRO=0.98`、`CF_ACC=0.02`、`OUT_ALPHA=0.3`、`ACC_LP_ALPHA=0.2`
  与原版逐行一致。
- 串口打印用的是 `sprintf` 定点格式化（`%ld.%02ld`），不依赖 newlib 的 `%f`
  （默认关闭浮点 printf，直接用 `%f` 会输出空）。
- 原版 `gz` 未使用、`HINGE_SIGN` 相同，保留以便对照。
- `Serial` 在 Blue Pill 的 Arduino core 下映射到 **USART1 (PA9/PA10)**，与接线表一致。