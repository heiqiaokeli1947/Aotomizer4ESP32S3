# 雾化控制器设计文档 (DESIGN.md)

## 1. 项目概述

### 1.1 项目定位
基于 **ESP32-S3** 的智能雾化/降温控制器，运行 **MicroPython** 固件。集成多路传感器（温湿度、气压/海拔、双通道水质）、多路执行器（电磁阀、水泵、风扇），通过 WiFi 提供 Web 配置界面与实时监控。

### 1.2 核心特性
| 特性 | 说明 |
|------|------|
| 自动雾化 FSM | 根据翅片温度/环境湿度智能启停喷雾 |
| 水循环 FSM | 自动检测水箱水位、控制进水/排水 |
| 双通道 TDS | 进水 + 水箱水质实时监测 |
| Web 管理界面 | 单页应用，参数设置/实时监控/网络配置 |
| WiFi 双模式 | AP 热点 + STA 连接 |
| 数据持久化 | BTree 数据库保存配置和统计数据 |
| 状态指示灯 | WS2812 RGB LED 显示系统状态 |
| 看门狗保护 | WDT 防止系统卡死 |

### 1.3 技术栈
| 类别 | 技术 |
|------|------|
| MCU | ESP32-S3-WROOM-1 |
| 固件 | MicroPython 1.25 |
| Web 框架 | Microdot |
| 数据库 | ubtree (BTree) |
| 前端 | 原生 JavaScript + jQuery + Spectre CSS |
| 传感器协议 | I²C (BMP280, HDC1080) + UART (TDS) |

---

## 2. 目录结构

```
Aotomizer4ESP32S3/
├── boot.py                    # MicroPython 启动脚本（当前为空）
├── main.py                    # 主入口：Web 服务、FSM 调度、数据存储
├── mydb                       # BTree 数据库文件（运行时生成）
├── .gitignore
├── README.md
│
├── domain/                    # 业务逻辑层
│   ├── AotomizerFSM.py        # 雾化状态机（核心逻辑）
│   ├── WaterProcessFSM.py     # 水循环状态机
│   ├── sensorData.py          # 全局传感器数据容器（单例）
│   ├── DBUtils.py             # BTree 数据库读写工具
│   ├── wifi.py                # WiFi 连接管理
│   ├── AACOps.py              # 空调控制操作
│   ├── LogUtils.py            # 日志工具
│   └── fileUtils.py           # 文件工具
│
├── driver/                    # 驱动层
│   ├── bsp.py                 # 板级支持包（单例，硬件初始化与访问）
│   ├── bmp280.py              # BMP280 气压/温度/海拔传感器驱动
│   ├── hdc1080.py             # HDC1080 温湿度传感器驱动
│   ├── tds.py                 # TDS 水质传感器驱动（双通道 UART）
│   └── enum.py                # 枚举定义（EV/Switch/WaterMark）
│
├── lib/                       # 第三方库
│   └── microdot.py            # 轻量级 Web 框架
│
├── static/                    # 前端静态资源
│   ├── index.html             # 主页面（单文件 SPA）
│   ├── index_backup.html      # 备份页面
│   ├── jquery.min.js          # jQuery
│   ├── spectre.min.css        # Spectre CSS 框架
│   ├── sweetalert.min.js      # 弹窗组件
│   ├── chart.umd.js           # 图表组件
│   └── favicon.ico
│
└── Doc/                       # 文档
    ├── DESIGN.md              # 本设计文档
    ├── TDS模块信息.txt
    └── 页面优化方案.txt
```

---

## 3. 硬件资源使用情况

### 3.1 引脚映射总表

| 硬件类别 | 硬件名称 | 引脚/端口 | 使用状态 | 用途描述 |
|----------|----------|-----------|----------|----------|
| **GPIO 输出** | 雾化电磁阀1 | GPIO11 | 使用中 | 控制第1路喷雾头电磁阀开关 |
| **GPIO 输出** | 雾化电磁阀2 | GPIO12 | 使用中 | 控制第2路喷雾头电磁阀开关 |
| **GPIO 输出** | 雾化电磁阀3 | GPIO13 | 使用中 | 控制第3路喷雾头电磁阀开关 |
| **GPIO 输出** | 进水电磁阀 | GPIO14 | 使用中 | 控制水箱进水电磁阀 |
| **GPIO 输出** | 废水电磁阀 | GPIO21 | 使用中 | 控制水箱排水电磁阀 |
| **GPIO 输出** | WS2812 LED | GPIO48 | 使用中 | RGB 状态指示灯（1颗） |
| **GPIO 输入** | 水箱高水位传感器 | GPIO15 (PULL_UP) | 使用中 | 检测水箱是否满水，低电平有效 |
| **GPIO 输入** | 水箱低水位传感器 | GPIO16 (PULL_UP) | 使用中 | 检测水箱是否缺水，低电平有效 |
| **GPIO 输入** | 系统使能开关 | GPIO4 (PULL_DOWN) | 使用中 | 系统总开关，高电平使能 |
| **GPIO 输入** | 喷雾使能开关 | GPIO5 (PULL_DOWN) | 使用中 | 喷雾功能使能，高电平允许喷雾 |
| **GPIO 输入** | 空调强制使能 | GPIO6 (PULL_DOWN) | 使用中 | 强制空调运行信号 |
| **GPIO 输入** | 空调霍尔传感器 | GPIO7 (PULL_DOWN) | 使用中 | 检测空调压缩机运行状态，高电平表示运行 |
| **PWM 输出** | 雾化水泵 | GPIO10 (PWM1) | 使用中 | 水泵转速调节，频率 25kHz |
| **PWM 输出** | 风扇电源控制 | GPIO46 (PWM2) | 使用中 | 风扇 MOS 管开关，0=全断,1023=全通 |
| **PWM 输出** | 风扇转速控制 | GPIO9 (PWM3) | 使用中 | 风扇转速 PWM 调节，频率 25kHz |
| **PWM 输出** | PWM 通道4 | GPIO 预留 | 可用 | 预留扩展，可用于额外风扇或水泵 |
| **UART** | UART1 | GPIO17(RX) / GPIO18(TX) | 使用中 | TDS 水质传感器串口通信（38400bps） |
| **UART** | UART0 | 默认引脚 | 可用 | 预留扩展，可用于调试或其他串口设备 |
| **I²C** | 软件 I²C | SCL=GPIO3 / SDA=GPIO8 | 使用中 | 连接 BMP280 和 HDC1080 传感器，100kHz |
| **I²C 设备** | BMP280 | 地址 0x76 | 使用中 | 气压/温度/海拔传感器 |
| **I²C 设备** | HDC1080 | 地址 0x40 | 使用中 | 温湿度传感器 |
| **串口传感器** | TDS 水质模块 | UART1 | 使用中 | 双通道 TDS 检测（通道1=进水，通道2=水箱） |
| **定时器** | Timer(1) | - | 使用中 | 传感器数据采集定时触发（1秒周期） |
| **定时器** | Timer(0/2/3) | - | 可用 | 预留扩展 |
| **ADC** | ADC 通道 | - | 可用 | 预留扩展，可用于模拟量传感器 |
| **SPI** | SPI 总线 | - | 可用 | 预留扩展，可用于 SD 卡或其他 SPI 设备 |
| **WiFi** | WiFi 模块 | - | 使用中 | 无线网络连接 + AP 热点配置 |
| **看门狗** | WDT | - | 使用中 | 系统看门狗，60秒超时保护 |

### 3.2 PWM 通道映射详解

| PWM 通道 | 引脚 | 硬件 | 配置参数 | 说明 |
|----------|------|------|----------|------|
| PWM1 | GPIO10 | 雾化水泵 | pwm1freq, pwm1min, pwm1max, pwm1default | 控制水泵转速，影响喷雾量 |
| PWM2 | GPIO46 | 风扇电源 MOS | pwm2freq, pwm2min, pwm2max, pwm2default | 仅用于电源开关（0 或 1023） |
| PWM3 | GPIO9 | 风扇转速 | pwm3freq, pwm3min, pwm3max, pwm3default | 风扇转速精细调节 |
| PWM4 | 预留 | - | pwm4freq, pwm4min, pwm4max, pwm4default | 保留配置接口，硬件未接入 |

### 3.3 PWM 初始化代码位置
`driver/bsp.py:103-107`：
```python
self.__pwmWaterBump = PWM(Pin(10), freq=int(self.config["pwm1freq"]), duty=int(self.config["pwm1default"]))
self.__fan1PwmPin = PWM(Pin(46), freq=int(self.config["pwm2freq"]), duty=int(self.config["pwm2default"]))
self.__fan2PwmPin = PWM(Pin(9), freq=int(self.config["pwm3freq"]), duty=int(self.config["pwm3default"]))
```

---

## 4. 系统架构

### 4.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        main.py                                   │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────────────────┐  │
│  │ Web App  │  │  FSM Scheduler │  │  Timer + Watchdog + Save │  │
│  └────┬─────┘  └──────┬─────────┘  └───────────┬──────────────┘  │
│       │               │                        │                 │
│       ▼               ▼                        ▼                 │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    domain 业务层                           │   │
│  │  ┌──────────────┐  ┌───────────────┐  ┌────────────────┐  │   │
│  │  │ AotomizerFSM │  │ WaterProcessFSM│  │  sensorData   │  │   │
│  │  └──────┬───────┘  └───────┬───────┘  └───────┬────────┘  │   │
│  │         │                  │                  │            │   │
│  │  ┌──────┴──────────────────┴──────────────────┴────────┐   │   │
│  │  │              DBUtils (BTree 持久化)                  │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  └───────────────────────────────────────────────────────────┘   │
│       │               │                        │                 │
│       ▼               ▼                        ▼                 │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    driver 驱动层 (BSP 单例)                │   │
│  │  ┌────────┐ ┌──────┐ ┌──────┐ ┌───────┐ ┌──────────────┐  │   │
│  │  │bmp280  │ │hdc   │ │ tds  │ │ GPIO  │ │ PWM 3通道    │  │   │
│  │  └──┬─────┘ └──┬───┘ └──┬───┘ └───┬───┘ └──────┬───────┘  │   │
│  │     │    I²C    │   UART          │             │          │   │
│  └─────┼───────────┼──────────────────┼─────────────┼──────────┘   │
│        ▼           ▼                  ▼             ▼              │
│  ┌─────────────────────────────────────────────────────────┐      │
│  │                 ESP32-S3 硬件                           │      │
│  └─────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                 浏览器 (index.html SPA)                          │
│  ┌─────────────────────────────────────────────────────────┐      │
│  │  系统监控 │ 参数设置 │ 网络设置 │ 日志（4个Tab）          │      │
│  └─────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 模块职责

| 模块 | 职责 | 运行周期 |
|------|------|----------|
| **main.py** | 主入口、Web 服务、FSM 调度、定时器回调 | 持续 |
| **BSP (driver/bsp.py)** | 硬件初始化、传感器读取、执行器控制 | 被调用 |
| **AotomizerFSM** | 雾化逻辑状态机 | 主循环轮询 |
| **WaterProcessFSM** | 水循环逻辑状态机 | 主循环轮询 |
| **sensorData** | 全局数据容器 | 被引用 |
| **DBUtils** | BTree 数据库 KV 读写 | 被调用 |
| **wifi** | WiFi 连接管理（自动重连、AP/STA 切换） | 后台循环 |

---

## 5. 核心模块详解

### 5.1 main.py — 主入口

**运行时序：**
```
boot → WiFi 连接 → 传感器初始化 → Timer(1) 启动（1秒周期）
  → Web 服务启动 → 主循环（FSM 调度 + WDT 喂狗 + 数据保存）
```

**主循环职责：**
1. 调度 `WaterProcessFSM.tick()`
2. 调度 `AotomizerFSM.tick()`
3. WDT 喂狗
4. 定时保存传感器数据到数据库

**Timer 回调 (`timerHandler`)：** 每 1 秒触发
1. 调用 BSP 的 `readBmp280` → 气压/温度/海拔
2. 调用 BSP 的 `readHdc1080` → 温湿度
3. 调用 BSP 的 `_tdsTick()` → TDS 异步状态机
4. 读取水箱水位传感器（高/低）
5. 计算湿球温度

**Web API 路由（Microdot）：**

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 返回 index.html |
| `/favicon.ico` | GET | 返回图标 |
| `/static/<path>` | GET | 静态资源服务 |
| `/status` | GET | 查询系统状态 / 设置参数（通过 mode=get/set 区分） |
| `/scanap` | GET | 扫描周围 WiFi AP |
| `/setwifi` | GET | 设置 WiFi SSID 和密码 |
| `/reset` | GET | 恢复出厂配置 |
| `/restart` | GET | 重启设备 |

**配置数据库参数（节选共 50+ 项）：**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| pwm1freq / pwm2freq / pwm3freq | int | PWM 频率（默认 25000） |
| pwm1min / pwm2min / pwm3min | int | PWM 最小占空比（0-100） |
| pwm1max / pwm2max / pwm3max | int | PWM 最大占空比（0-100） |
| pwm1default / pwm2default / pwm3default | int | PWM 默认占空比 |
| sprayPeriod | int | 喷雾周期（秒，默认 40） |
| minSparyTime / maxSparyTime | int | 单次喷雾最短/最长时间（秒） |
| minAddWaterInterval | int | 最小补水间隔（秒） |
| waterDischargeTimeOut / waterFillTimeOut | int | 排水/进水超时（秒） |
| fineHThreshold / fineLThreshold | float | 翅片温度高/低阈值（℃） |
| fineTempThreshold | float | 翅片温度临界阈值（℃） |
| waterTDSThreshold | int | 水箱 TDS 阈值（ppm，超过则排水） |
| modbusSlaveAddr / modbusBadud | int | Modbus 从机地址 / 波特率 |
| latitude / longitude / altitude | float | 地理位置 |
| wifiname / wifipwd | str | 目标 WiFi 名称 / 密码 |
| sw1 / sw1name, sw2 / sw2name | bool/str | 2路开关量及其名称 |
| serverurl | str | 远程服务器地址 |

### 5.2 BSP (driver/bsp.py) — 板级支持包

**设计模式：** 单例（`__new__`）

**初始化流程（`__init__`）：**
```
1. 创建 SoftI2C(SCL=Pin(3), SDA=Pin(8), freq=100000)
2. 创建 WS2812 NeoPixel(Pin(48), 1)
3. 初始化所有 GPIO（电磁阀、传感器、开关）
4. 创建 SensorData 单例
5. 初始化 BMP280、HDC1080、TDS 传感器
6. 初始化 PWM（3 通道）
```

**关键方法：**

| 方法 | 功能 |
|------|------|
| `initHW(config)` | 执行硬件初始化（创建 PWM、读取初始传感器值） |
| `readBmp280()` | 读取气压/温度/海拔，失败返回 -9999 |
| `readHdc1080()` | 读取温湿度，失败返回 -9999 |
| `_tdsTick()` | TDS 异步状态机轮询（每 1 秒调用） |
| `setWaterPump(percent)` | 设置水泵 PWM 占空比（0-100%） |
| `setFan1Pwm(percent)` | 设置风扇 PWM：PWM2 电源 + PWM3 转速 |
| `openEV(evType)` / `closeEV(evType)` | 打开/关闭指定电磁阀 |
| `getWaterMark()` | 读取水箱水位，返回 enum.WaterMark |
| `isSysEnabled()` / `isSprayEnabled()` | 读取系统/喷雾使能开关 |
| `isACHallActive()` | 读取空调霍尔传感器 |
| `setLEDArray(color)` | 设置 WS2812 LED 颜色 |

### 5.3 雾化状态机 (domain/AotomizerFSM.py)

**设计模式：** 状态机（FSM）

**喷雾逻辑核心：**
- 翅片温度 > `fineHThreshold` + 湿度 < `fineHThreshold` → 开始喷雾
- 翅片温度 < `fineLThreshold` → 停止喷雾
- 单次喷雾时长 ≥ `maxSparyTime` → 强制停止
- 喷雾间隔 ≥ `sprayPeriod` → 允许再次喷雾

**状态枚举（STATUS）：**
| 状态值 | 名称 | 说明 |
|--------|------|------|
| 0 | IDLE | 空闲 |
| 1 | SPRAY_WATER_1 | 喷雾通道1 |
| 2 | SPRAY_WATER_2 | 喷雾通道2 |
| 3 | SPRAY_WATER_3 | 喷雾通道3 |
| 4 | WAIT_NEXT_PERIOD | 等待下一个喷雾周期 |

**`tick()` 执行逻辑：**
```
1. 读取翅片温度/湿度
2. 根据状态执行对应动作
3. 更新 totalSprayCount 统计
```

### 5.4 水循环状态机 (domain/WaterProcessFSM.py)

**设计模式：** 状态机（FSM）

**状态枚举：**
| 状态值 | 名称 | 说明 |
|--------|------|------|
| 0 | IDLE | 空闲 |
| 1 | WAIT | 等待补水（低水位触发） |
| 2 | FILLING | 正在进水 |
| 3 | DISCHARGING | 正在排水 |

**补水逻辑：**
- 低水位触发进水
- 进水量超 `waterFillTimeOut` → 超时退出
- 高水位检测到 → 停止进水
- 进水量累计 → 更新 `totalAddWaterCount`

**排水逻辑：**
- 当 TDS 超过阈值 `waterTDSThreshold` → 自动排水补水

### 5.5 sensorData (domain/sensorData.py) — 全局数据容器

**设计模式：** 单例 + 属性访问

**包含字段（全部提供 property）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| temp | float | BMP280 温度（℃） |
| presure | float | BMP280 气压（Pa） |
| altitude | float | 海拔高度（m） |
| fineTemp | float | 翅片温度（HDC1080，℃） |
| humi | float | 环境湿度（%RH） |
| wetBulbTemp | float | 湿球温度（℃，计算值） |
| inWaterTDS | float | 进水 TDS（ppm） |
| inWaterTemp | float | 进水温度（℃） |
| waterTankTDS | float | 水箱 TDS（ppm） |
| waterTankTemp | float | 水箱温度（℃） |
| waterMark | enum.WaterMark | 水箱水位 |
| airConditionerStatus | int | 空调运行状态（0=停止，1=运行） |

**无效值约定：** `-9999` 表示传感器读取失败。

### 5.6 DBUtils (domain/DBUtils.py) — 数据库工具

**底层技术：** ubtree (MicroPython BTree)

**数据库文件：** `mydb`（相对路径）

**重要限制：** BTree 数据库 key 和 value 均为字符串类型，所有值需序列化存储。

**提供方法：**

| 方法 | 功能 |
|------|------|
| `openDB()` | 打开/创建数据库 |
| `closeDB()` | 关闭数据库 |
| `save(key, value)` | 保存 KV（自动 flush） |
| `get(key, default="")` | 读取 KV，不存在返回默认值 |
| `getAll(verbose=False)` | 读取全部 KV 到 dict |
| `set(k, v)` | 直接设置 KV（调用 save） |
| `delete(key)` | 删除 KV |
| `count()` | 返回 KV 总数 |
| `contains(key)` | 检查 key 是否存在 |

**使用示例：**
```python
from domain.DBUtils import DBUtils
DBUtils.save("fineHThreshold", "36.0")
val = DBUtils.get("fineHThreshold")  # 返回 "36.0"
```

**类型转换注意：** DB 中存储的是字符串，使用时需要手动转换：
```python
thd = float(DBUtils.get("fineHThreshold", "36.0"))
```

---

## 6. 传感器驱动详解

### 6.1 BMP280 (driver/bmp280.py)

| 属性 | 值 |
|------|-----|
| 类型 | I²C 气压/温度传感器 |
| 地址 | 0x76 |
| 硬件 I²C | 软件 I²C（SoftI2C） |
| 热插拔 | ✅ 支持（`hardWareReady` 自动重连） |
| 无效值 | -9999 |

**热插拔机制：**
- 所有 I²C 操作包裹在 `try/except (OSError, TypeError)` 中
- 异常时设置 `hardWareReady = False`
- 下次 `get()` 调用时检测到 `hardWareReady == False` 会自动重新 `initHardware()`

**关键设计：**
- 异常时立即将 T/P 重置为 -9999（不会使用过期数据）
- `getAltitude()` 在压力无效时直接返回 -9999

### 6.2 HDC1080 (driver/hdc1080.py)

| 属性 | 值 |
|------|-----|
| 类型 | I²C 温湿度传感器 |
| 地址 | 0x40 |
| 热插拔 | ✅ 支持（同 BMP280 模式） |
| 硬件校验 | ❌ 无校验码，依赖 I²C ACK |
| 无效值 | -9999 |

**数据校验策略：**
- 依赖 I²C 总线层的 ACK 确认
- MicroPython 层不做额外 CRC 校验
- 业务层通过异常捕获保证无效值传递

### 6.3 TDS (driver/tds.py)

| 属性 | 值 |
|------|-----|
| 类型 | UART 水质传感器 |
| 串口 | UART1, 38400bps |
| 通道数 | 2（通道1=进水，通道2=水箱） |
| 帧格式 | 18 字节（固定头 0xAA 0x55 + 数据 + 校验和） |
| 热插拔 | ✅ 基本支持（UART 恢复稳定后可重新通信） |
| 无效值 | -9999.0 |

**异步状态机设计（2026-06 重构）：**

```
状态机：
  _STATE_IDLE(0)    → 空闲，等待 start_read()
  _STATE_WAITING(1) → 已发送指令，等待响应

接口：
  start_read(channel) → 发送读指令，返回是否成功
  poll()              → 非阻塞轮询，返回结果 dict 或 None
```

**轮询超时：** 3000ms（保证在 3 秒内有机会接收完整帧）

**帧解析流程：**
1. `poll()` 检查 `uart.any()` 是否有数据
2. `uart.read()` 读取并追加到 `rx_buf`
3. `rx_buf` ≥ 18 字节时调用 `_find_valid_frame()`
4. 验证帧头 (0xAA 0x55) 和校验和
5. 提取 TDS 值（4 字节 float）和温度（4 字节 float）

**BSP 集成方式 (`_tdsTick`)：**
- Timer(1) 每 1 秒触发一次 `_tdsTick()`
- 使用状态机顺序读取 2 个通道
- 第 1 秒：`start_read(1)` → 状态切 WAITING
- 第 2 秒（Timer 再触发）：`poll()` 拿到通道1数据 → `start_read(2)`
- 第 3 秒：`poll()` 拿到通道2数据 → 回到 IDLE
- 若超时或校验失败：`poll()` 返回 None → 数据保持 -9999.0

**关键改进：**
- 消除 Timer 回调中的阻塞 `time.sleep_ms()`
- 使用 `uart.read()` 前先判空，避免 NoneType 错误
- 失败时立即将数据置为 -9999.0（而非保持旧值）

### 6.4 I²C 总线特性

| 项目 | 当前配置 |
|------|----------|
| 实现方式 | 软件 I²C (SoftI2C) |
| SCL/SDA | GPIO3 / GPIO8 |
| 速率 | 100kHz (Standard Mode) |
| 总线设备数 | 2 (BMP280 + HDC1080) |
| 连接距离 | 约 1.5 米 |
| 上拉电阻 | 需外置（BSP 未启用内部上拉） |
| 建议上拉 | 2.2kΩ 或 4.7kΩ |

**通信距离分析：**
- 标准 I²C 理论最大距离取决于 SDA/SCL 的电容负载
- 100kHz 模式下，1.5 米连线 **完全稳定**
- 若需要更长距离，建议：
  - 降低速率到 10kHz
  - 使用 I²C 缓冲器（如 PCA9306）
  - 减小上拉电阻（增强驱动能力）

---

## 7. Web API 详细设计

### 7.1 `/status` — 系统状态查询与参数设置

**请求方式：** GET

**mode 参数区分两种模式：**

#### mode=get（查询）
返回完整系统状态 JSON：

```json
{
  "errCode": "0",
  "errMsg": "success",
  // --- 传感器数据 ---
  "temp": 23.85,
  "presure": 100530,
  "altitude": 498,
  "fineTemp": 23.85,
  "humi": 70.22,
  "wetBulbTemp": 19.92,
  "inWaterTDS": 14.3,
  "inWaterTemp": 24.0,
  "waterTankTDS": 14.05,
  "waterTankTemp": 24.5,
  "waterMark": 3,
  "waterAvailable": true,
  "airConditionerStatus": 0,
  "runTime": 921,
  // --- 配置参数 ---
  "mode": "normal",
  "sprayPeriod": 40,
  "minSparyTime": 5,
  "maxSparyTime": 12,
  "minAddWaterInterval": 2400,
  "waterTDSThreshold": 80,
  "fineHThreshold": 36.0,
  "fineLThreshold": 24.0,
  "pwm1freq": 25000,
  "pwm1min": 15,
  "pwm1max": 100,
  "pwm1default": 0,
  "pwm2freq": 25000,
  "pwm2min": 15,
  "pwm2max": 100,
  "pwm2default": 0,
  "pwm3freq": 25000,
  "pwm3min": 15,
  "pwm3max": 100,
  "pwm3default": 0,
  // --- 开关 ---
  "sw1": true, "sw1name": "S1",
  "sw2": false, "sw2name": "S2",
  // --- 网络 ---
  "wifiname": "cissco_2g",
  "wifipwd": "xxx",
  // --- 统计 ---
  "totalSprayCount": 3748,
  "totalRunTime": 200456,
  "totalAddWaterCount": 4,
  // --- 设备信息 ---
  "deviceId": "E8F60A8A5500",
  "devicename": "Aotomizer",
  "ver": "1.1"
}
```

**waterMark 枚举值：**
| 值 | 含义 |
|----|------|
| 1 | 空 |
| 2 | 正常 |
| 3 | 满 |

**runTime 说明：** 本次开机以来运行的秒数（从 bootTime 起计时）

#### mode=set（设置参数）
通过 query string 传入需要设置的参数，支持 UTF-8 编码：

```
/status?mode=set&devicepwd=xxx&fineHThreshold=36.0&fineLThreshold=24.0
&pwm1freq=25000&pwm1min=15&pwm1max=100&pwm1default=0
&sw1=true&sw2=false&sw1name=开关1&sw2name=开关2
```

**注意事项：**
- `devicepwd` 参数必须正确
- 所有 PWM 通道参数需同时下发（pwm1~pwm4 的 freq/min/max/default）
- 参数值通过 `urllib.parse.unquote` 解码，支持 UTF-8 中文
- 布尔值通过自定义 `_parseBool` 函数解析（支持 true/false/0/1/on/off）

### 7.2 `/scanap` — WiFi 扫描

返回周围 WiFi AP 列表（JSON）：
```json
{
  "errCode": "0",
  "aps": ["WiFi-2.4G", "OfficeWiFi", "..."]
}
```

### 7.3 `/setwifi` — 设置 WiFi

```
/setwifi?ssid=xxx&pwd=xxx
```

设置后立即尝试连接，可通过 `/scanap` 确认。

### 7.4 `/reset` — 恢复出厂

清除所有用户配置，恢复默认值。

### 7.5 `/restart` — 重启设备

调用 `machine.reset()` 重启。

---

## 8. 前端架构 (static/index.html)

### 8.1 技术选型
| 类别 | 技术 |
|------|------|
| 框架 | 单文件 SPA（原生 JS + jQuery） |
| 样式 | Spectre CSS（响应式） |
| 弹窗 | SweetAlert |
| 图表 | Chart.js |

### 8.2 页面结构（Tab 标签页）

```
┌─────────────────────────────────────────────────────────────┐
│  [系统监控]  [参数设置]  [网络设置]                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Tab 1: 系统监控                                            │
│  ├── 实时数据卡片（温湿度、TDS、水位、空调状态）             │
│  ├── 运行状态显示（FSM 状态、喷雾计数）                      │
│  └── 趋势图表                                                │
│                                                             │
│  Tab 2: 参数设置                                            │
│  ├── 喷雾参数组（阈值、周期、TDS 阈值）                      │
│  ├── PWM 参数组（3 通道独立配置）                            │
│  ├── 开关参数组（sw1/sw2 + 中文名称）                        │
│  └── 应用 / 重置按钮                                        │
│                                                             │
│  Tab 3: 网络设置                                            │
│  ├── AP 扫描列表                                            │
│  ├── SSID / Password 输入                                   │
│  └── 连接测试                                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 核心模块

| 模块 | 说明 |
|------|------|
| `CONFIG` | 全局配置（API 地址、刷新间隔、参数分组定义） |
| `UTILS.nv(v, def)` | 无效值处理：`undefined/null/-9999 → def`，**保留 0** |
| `DeviceModel` | 后端数据解析类，将 raw JSON 转为前端可用格式 |
| `createRefreshController()` | 刷新控制器，定时拉取 `/status` 并更新所有视图 |
| `createEventController()` | 事件控制器，处理按钮点击、Tab 切换等交互 |
| `Views[]` | 数组，每个 Tab 一个独立视图函数（工厂模式） |

### 8.4 数据处理关键函数

```javascript
// 核心：正确处理后端的无效值（-9999）和零值（0）
var nv = function(v, def) {
    if (v === undefined || v === null) return def;
    if (typeof v === 'number' && v === -9999) return def;
    return v;
};
```

**问题历史：** 早期实现用 `rawData.inWaterTDS || invalid`，当后端返回 `0.0`（TDS 读数为 0 ppm）时被误判为无效值，导致 TDS 始终显示 `----`。改用 `nv()` + 严格类型检查解决。

### 8.5 参数分组定义（后端 CONFIG 配置）

```javascript
PARAM_GROUPS = [
    {
        name: "喷雾参数",
        params: [
            "fineHThreshold", "fineLThreshold", "fineTempThreshold",
            "sprayPeriod", "minSparyTime", "maxSparyTime",
            "minAddWaterInterval", "waterTDSThreshold"
        ]
    },
    {
        name: "PWM 参数",
        perChannel: true,
        channels: 4,
        channelLabels: ["水泵", "风扇电源", "风扇转速", "预留"],
        perChannelParams: ["freq", "min", "max", "default"]
    },
    {
        name: "开关配置",
        params: ["sw1", "sw1name", "sw2", "sw2name"]
    }
];
```

---

## 9. 数据流

### 9.1 传感器数据流

```
Timer(1) 1秒周期
    │
    ▼
BSP._sensorTick()
    │
    ├──► bmp280.get() ──► sensorData.temp / presure / altitude
    │
    ├──► hdc1080.get() ──► sensorData.fineTemp / humi
    │
    ├──► tds._tdsTick() ──► sensorData.inWaterTDS / inWaterTemp
    │                     └──► sensorData.waterTankTDS / waterTankTemp
    │
    └──► waterMark 读取 ──► sensorData.waterMark
                          └──► sensorData.waterAvailable
```

### 9.2 参数设置数据流

```
前端 Apply 按钮
    │
    ▼
收集所有参数（PWM1~PWM4 全部通道）
    │
    ▼
GET /status?mode=set&key1=val1&...
    │
    ▼
main.py handler()
    ├── devicepwd 校验
    ├── urllib.parse.unquote（中文解码）
    ├── DBUtils.save(key, str(value)) → 持久化
    ├── DBUtils 存为字符串，使用时再类型转换
    │
    ▼
刷新 BSP config 缓存 → BSP 运行时立即生效
```

### 9.3 主循环数据流

```
main.py sysTask() (while True)
    │
    ├──► WaterProcessFSM.tick() → 控制进水/排水
    │       ├── 读 sensorData.waterMark
    │       ├── 读 sensorData.waterTankTDS（TDS 阈值判断）
    │       └── 写 EV 电磁阀
    │
    ├──► AotomizerFSM.tick() → 控制喷雾
    │       ├── 读 sensorData.fineTemp / humi
    │       ├── 读系统/喷雾使能开关
    │       ├── 读 DBUtils 配置（阈值、周期）
    │       └── 写电磁阀 + 水泵 + 风扇
    │
    ├──► WDT.feed()
    │
    └──► 定时 DBUtils.save(totalRunTime / totalSprayCount ...)
```

---

## 10. 枚举常量定义 (driver/enum.py)

### EV — 电磁阀类型
| 值 | 含义 |
|----|------|
| WATER_INPUT_EV (1) | 进水电磁阀 |
| WASTE_WATER_EV (2) | 废水电磁阀 |
| WATER_SPRAY_EV_1 (3) | 喷雾电磁阀1 |
| WATER_SPRAY_EV_2 (4) | 喷雾电磁阀2 |
| WATER_SPRAY_EV_3 (5) | 喷雾电磁阀3 |

### Switch — 开关状态
| 值 | 含义 |
|----|------|
| OFF (0) | 关 |
| ON (1) | 开 |

### WaterMark — 水箱水位
| 值 | 含义 |
|----|------|
| EMPTY (1) | 空 |
| NORMAL (2) | 正常 |
| FULL (3) | 满 |

---

## 11. 配置参数类型转换说明

**核心问题：** DBUtils 基于 BTree 数据库，所有 key/value 都必须是字符串。

**解决方案：**
```
读取时：DBUtils.get(key, default) → 得到字符串
     │
     ├── 整数参数：int(val)
     ├── 浮点参数：float(val)
     └── 布尔参数：自定义 _parseBool(val)

保存时：DBUtils.save(key, str(value)) 统一转字符串
```

**`_parseBool` 函数（main.py）：**
```python
def _parseBool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ('true', '1', 'on', 'yes')
    return bool(val)
```

---

## 12. 无效值体系

**统一约定：** 任何传感器读取失败或数据无效时，驱动层必须立即返回 `-9999`（float 类型）。

| 驱动 | 无效值 | 设置时机 |
|------|--------|----------|
| BMP280 | -9999 | I²C 异常 / 校验失败 / var1==0 |
| HDC1080 | -9999 | I²C 异常 / 转换失败 |
| TDS | -9999.0 | 串口超时 / 校验失败 / 无响应 |
| 其他统计参数 | -9999 | 硬件读取失败 |

**防止使用过期数据：** 驱动必须在检测到失败时**立即**将结果置为 -9999，而不是保留上次成功的读数。这样业务层（FSM）不会基于陈旧数据做出错误判断。

---

## 13. WiFi 模块 (domain/wifi.py)

**功能：**
- STA 模式：连接指定 SSID
- AP 模式：热点 `IOT_2G`，IP `192.168.30.1`
- 自动重连机制
- IP 广播（UDP 广播到 LAN）

---

## 14. 版本历史

| 版本号 | 日期 | 说明 |
|--------|------|------|
| 202606230001 | 2026-06-23 | 文档创建，记录基本架构 |
| 202606230002 | 2026-06-23 | 增加 PWM 参数映射错误说明，修复风扇用 pwm1 的问题 |
| 202606230003 | 2026-06-23 | 增加 DBUtils 新增方法说明、热插拔分析、I²C 通信距离 |
| 202606240000 | 2026-06-24 | **全量刷新**：纠正 PWM 引脚映射表（PWM1=Pin10水泵, PWM2=Pin46风扇电源, PWM3=Pin9风扇转速）；重写系统架构图；补充 TDS 异步状态机设计；增加无效值体系说明；完善前端架构描述；补充 runTime/waterTDSThreshold 等新增参数；更新传感器热插拔支持说明 |
| 202606250000 | 2026-06-25 | 二次重构 TDS 驱动为异步非阻塞（消除 Timer 回调中的 sleep）；修复 BMP280 get() 方法 var1==0 时未重置 T/P 的问题；修复 BMP280 getAltitude() 未检查无效压力；修复前端 nv() 函数处理 0.0 值；修正所有驱动在读取失败时立即置为 -9999 的行为 |

---

## 15. 待办事项 / Known Issues

| # | 描述 | 优先级 |
|---|------|--------|
| 1 | PWM4 通道硬件未接线，配置参数保留但无物理作用 | 低 |
| 2 | boot.py 当前为空，可考虑启用 WeBREPL | 低 |
| 3 | HDC1080 无硬件 CRC 校验，数据正确性依赖 I²C ACK | 中 |
| 4 | BMP280 和 HDC1080 共用同一组 I²C 引脚，热插拔会相互影响 | 中 |
| 5 | main.py status handler 中参数类型转换逻辑较分散，可考虑统一封装 | 低 |
| 6 | 无 OTA 更新能力 | 低 |
