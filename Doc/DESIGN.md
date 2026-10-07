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
| 看门狗保护 | WDT 防止系统卡死（活性检测式条件喂狗） |
| NTP 网络对时 | 联网后 SNTP 校时 RTC 为北京时间，首次成功后每 1 周自动重校 |
| 全局日志时间戳 | 统一 `log()` 输出，带 `[YYYY-MM-DD HH:MM:SS]` 前缀 |

### 1.3 技术栈
| 类别 | 技术 |
|------|------|
| MCU | ESP32-S3-WROOM-1 |
| 固件 | MicroPython v1.28.0（2026-04-06 构建，Generic ESP32S3 Octal-SPIRAM；2026-10-07 板端实测，原记录 v1.25.0 已更新） |
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
│   ├── ntpSync.py             # NTP 网络对时（联网后同步 RTC 为北京时间）
│   ├── AACOps.py              # 空调控制操作
│   ├── LogUtils.py            # 全局日志工具（log() 输出带 [日期 时间] 前缀）
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
| **UART** | UART1 | GPIO17(RX) / GPIO18(TX) | 使用中 | TDS 水质传感器串口通信（9600bps） |
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

### 3.3 PWM 初始化与参数更新（2026-09-21 修复内存泄漏）
`driver/bsp.py`：PWM 对象**仅在首次 `setConfig()` 时构造**（`initHW()`），此后参数变更走 `updatePWM()` 原地更新 `freq()/duty()`，不再重建对象：
```python
# initHW()：首次构造（bsp.py:111-117）
self.__pwmWaterBump = PWM(Pin(10),freq=int(self.config["pwm1freq"]), duty=int(self.config["pwm1default"]))
self.__fan1PwmPin = PWM(Pin(46),freq=int(self.config["pwm2freq"]), duty=int(self.config["pwm2default"]))
self.__fan2PwmPin = PWM(Pin(9),freq=int(self.config["pwm3freq"]), duty=int(self.config["pwm3default"]))

# updatePWM()：参数变更原地更新（bsp.py:119-127），不重建对象；泵（pwm1）由 FSM
# 独占控制故被跳过（P1-5：运行中保存配置不得把泵 duty 强制回 pwm1default(0)，
# 否则正在进行的喷雾相位静默停泵），pwm1 参数变更下次上电 initHW() 时生效
```
原实现 `setConfig()` 每次都调用 `initHW()` 重建 3 个 PWM 对象——Web 保存一次参数即触发一次重复构造-丢弃循环（累积待 GC 的 PWM 对象与硬件通道重绑定开销），且运行中重建导致水泵/风扇输出瞬间毛刺，已修复。

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
| **ntpSync** | SNTP 网络对时（UTC+8 写入 RTC，仅联网后生效） | 主循环轮询 |
| **LogUtils** | 全局日志 `log()`（带 [日期 时间] 前缀） | 被调用 |

---

## 5. 核心模块详解

### 5.1 main.py — 主入口

**运行时序：**
```
boot → WiFi 连接 → 传感器初始化 → Timer(1) 启动（1秒周期）
  → Web 服务启动 → 主循环（FSM 调度 10Hz + NTP 对时轮询 + 定时任务；WDT 由 Timer(0) 条件喂狗）
```

**启动配置加载（2026-09-21 修复 F10）：**
- 从 DB 读取 `systemConfig` 后与 `defaulteSystemConfig` 合并：`dict(默认值) + update(存储值)`
- 老数据库缺少的新增字段自动取默认值，防止固件升级后访问缺失字段 KeyError 导致启动失败
- DB 内容损坏（JSON 解析失败或非 dict）时整体回退出厂默认，保证设备总能启动
- 合并结果不立即落库（避免每次开机写 Flash），下次保存配置时自然持久化

**主循环职责（10Hz 节拍，`utime.sleep_ms(100)`，2026-09-21 由 1Hz 提升）：**
1. 刷新主循环活性时间戳 `updateAliveTick()`
2. NTP 对时轮询 `tryNtpSync()`（未联网或未到期时立即返回，见 13.1）
3. 调度 `WaterProcessFSM.run()` + `AotomizerFSM.run()`（每轮各一次）
4. 定时任务——**全部基于真实时间判断（`ticks_diff >= 阈值`），与轮询频率解耦**：
   - GC + 内存报告：每 5 分钟
   - 状态 LED 翻转：每 2 秒（保持原节奏）
   - 统计落盘：每 1 小时
   - WiFi 断线重连：每 30 秒（normal 模式下检查 `isConnected()`，断线则调用 `wifi.startReconnect()` 做一次完整射频电源循环复位式重连，30s 周期即天然退避；函数内 `sleep(1)` 远小于喂狗 30s 活性窗口，不阻塞主循环）
   - `loopCounter` 仅保留为 feedDog 日志序号，不再参与定时判断

**看门狗机制（活性检测式喂狗，2026-09-21 修复 R1）：**
- WDT 超时 60s；Timer(0) 每 15s 触发 `feedDog` 回调
- 回调仅在 `utime.ticks_diff(now, lastAliveTick) < 30s` 时喂狗，否则打印告警并停止喂狗
- 主循环卡死 → 时间戳停止刷新 → 停止喂狗 → WDT 触发芯片复位
- 原实现由 Timer 回调无条件喂狗，主循环卡死时看门狗完全失效，已修复
- 30s 阈值安全性：开机 WiFi 连接最长阻塞约 36s（实测），但期间 t=15s/30s 两次喂狗仍在活性窗口内，主循环启动后立即刷新时间戳，不会误复位

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
| waterTDSThreshold | int | 水箱 TDS 阈值（ppm）——仅用于喷雾水质门控（≥ 阈值禁止喷雾）；无换水硬件，不触发排水 |
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

**喷雾逻辑核心（与代码一致，2026-09-21 刷新）：**
- 前置条件：空调运行中（霍尔传感器 `airConditionerStatus == ON`）且水箱有水（`waterAvailable`）
- 启动喷雾：空调开启 且 翅片温度 > `fineLThreshold` 且 水箱非空（`waterMark != EMPTY`，P1-8 防空水箱水泵干转）→ 进入 OVER_TEMP 并计算时长
- 停止/不喷雾：空调关闭、水箱无水或翅片温度 ≤ `fineLThreshold` → 回 READY
- **基准时长线性+偏置**（替代原阶梯式 if/elif）：翅片温度 = `fineLThreshold` → `minSparyTime`，达到 `fineHThreshold` → `maxSparyTime`，中间线性过渡、区间外钳位（`fineHThreshold` 由此参与控制；配置异常即高温阈值 ≤ 低温阈值时按最短时长兜底）
- **三路配比**：阀门安装位置上→下 = 1/2/3，阀门1 = 100%、阀门2 = 70%、阀门3 = 40%（不足 1 秒按 1 秒兜底），三路依次轮流喷雾
- 喷雾间隔：一轮结束后等待 `sprayPeriod` 秒（SPRAY_DELAY）才允许再次喷雾
- 湿度/湿球温度当前仅采集显示，未参与控制（待业务确认，见 15 节 F3）

**状态枚举（STATUS，与代码一致）：**
| 状态值 | 名称 | 说明 |
|--------|------|------|
| 0 | INIT | 初始化（初始化所有执行器到安全态） |
| 1 | READY | 就绪（等待空调开启） |
| 2 | AIR_CONDITIONER_ON | 空调运行中（检查是否超温） |
| 3 | OVER_TEMP | 翅片超温（检查水可用性，进入喷雾序列） |
| 4 | SPRAY_WATER_1 | 喷雾通道1（openSparyEV1，计时 spray1TimeOut） |
| 5 | SPRAY_WATER_2 | 喷雾通道2（openSparyEV2） |
| 6 | SPRAY_WATER_3 | 喷雾通道3（2026-09-21 修复 F1：openSparyEV3 已启用，三路轮流喷雾） |
| 7 | SPRAY_DELAY | 喷雾延时（等待 sprayPeriod） |

（2026-09-21 修复 F11：删除了从 WaterProcessFSM 复制残留的死方法 `checkWaterMark()`——它引用了本类 STATUS 中不存在的 `WATER_TANK_OK/WATER_TANK_NOT_OK` 及未初始化属性，且未挂入状态分发表，一旦误启用会立即崩溃）

**`run()` 执行逻辑（主循环 10Hz 每轮调用，2026-09-21 更正——入口为 `run()` 而非 tick()；计时已转毫秒）：**
```
1. 更新 runTimeCounterMs——开机以来的单调毫秒数，run() 内**逐轮累加** ticks_diff
   （每轮间隔约 100ms 恒在安全窗口内；不与开机快照做差，规避 6.21 天回绕，见 13.3）
2. 读取翅片温度/湿度/湿球温度与空调霍尔状态
3. 状态日志按时间节流（每 1s 打印一次，防 10Hz 刷屏）；距上次落盘 ≥ 1 小时（时间边沿触发）落盘 totalSprayCount
4. 按状态分发表执行当前状态动作（状态迁移见上表）
```
- 全部超时判定统一毫秒：`spray1/2/3TimeOut` 与 `sprayPeriod` 内部为 ms 值（config 仍填秒，读取处 ×1000），喷雾时长控制精度 100ms
- 原 `% 3600 == 0` 落盘写法在 10Hz 下同一秒会重复落盘 10 次，已改为"距上次 ≥ 1 小时"边沿触发
- `lastOverTempTime`（仅赋值从未参与判断）已删除

### 5.4 水循环状态机 (domain/WaterProcessFSM.py)

**设计模式：** 状态机（FSM）

**状态枚举：**
| 状态值 | 名称 | 说明 |
|--------|------|------|
| 0 | IDLE | 空闲 |
| 1 | WAIT | 等待补水（低水位触发） |
| 2 | FILLING | 正在进水 |
| 3 | DISCHARGING | 正在排水 |

**补水逻辑（计时基于 runTimeCounterMs 单调毫秒，见 13.3）：**
- 低水位触发进水
- 进水时长超 `waterFillTimeOut` → 超时退出
- 高水位检测到 → 停止进水
- 补水累计 → 更新 `totalAddWaterCount`（两次补水间隔受 `minAddWaterInterval` 限制）

**排水逻辑（计时基于 runTimeCounterMs 单调毫秒，见 13.3）：**
- 排水仅作为低水位补水的第一步（先排空管路残留再进水），由水位 `waterMark` 触发
- 排水时长由 `waterDischargeTimeOut` 控制，结束后转入进水
- **TDS 与排水无关（F4 决策 2026-09-22）**：无换水硬件，TDS 超阈值不触发任何排水/换水动作；`waterTDSThreshold` 唯一作用是喷雾水质门控（见 5.3 喷雾前置条件）

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

**线程安全（2026-09-21 修复 R2）：** 模块级 `dbLock = _thread.allocate_lock()`，Web 线程与主线程的所有数据库操作通过该锁串行化（btree 非线程安全，并发写可导致数据库损坏）。所有公开方法采用 `acquire → try/finally（操作 + closeDB + release）` 模式，任何异常都能保证释放锁并关闭数据库句柄。

**提供方法（模块级函数，非类）：**

| 方法 | 功能 |
|------|------|
| `openDB()` / `closeDB()` | 打开/关闭数据库（由各方法内部调用） |
| `save(kv)` | 批量保存 KV dict（自动 flush） |
| `get(k)` | 读取 KV，不存在返回 None |
| `multiGet(keys)` | 批量读取，缺失 key 返回 None |
| `getAll(verbose=False)` | 读取全部 KV 到 dict |
| `set(k, v)` | 设置单个 KV |
| `delete(k)` | 删除 KV（参数为标量 key，不能传 list） |
| `count()` | 返回 KV 总数 |
| `contains(k)` | 检查 key 是否存在 |

**使用示例：**
```python
import domain.DBUtils as db
db.save({"fineHThreshold": "36.0"})
val = db.get("fineHThreshold")  # 返回 "36.0"
```

**类型转换注意：** DB 中存储的是字符串，使用时需要手动转换：
```python
val = db.get("fineHThreshold") or "36.0"  # get 不带默认值参数，需自行处理 None
thd = float(val)
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
| 串口 | UART1, 9600bps（bsp 实例化时显式传入，TDS 模块固定波特率） |
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

**runTime 说明：** 本次开机以来运行的秒数，由主循环每轮毫秒精确累加（`runMs`），输出时才换算秒——与墙钟时间解耦，NTP 对时跳变不影响；且累计对象是每轮约 1s 的间隔，永远处于 `ticks_diff` 安全窗口（真实差值 < 2^29ms ≈ 6.21 天）内，长期运行不会回绕出错。`totalRunTime` 同为毫秒累计（`totalRunTimeMs`，DB 仍以秒存储，老数据兼容），每 3600 秒落盘一次；两个 FSM 内部的 `runTimeCounter` 采用同一模式（全部计时约定见 13.3）

#### mode=set（设置参数）
通过 query string 传入需要设置的参数，支持 UTF-8 编码：

```
/status?mode=set&devicepwd=xxx&fineHThreshold=36.0&fineLThreshold=24.0
&pwm1freq=25000&pwm1min=15&pwm1max=100&pwm1default=0
&sw1=true&sw2=false&sw1name=开关1&sw2name=开关2
```

**注意事项：**
- `devicepwd` 参数必须正确
- **数值参数先整体校验后应用（R4，2026-09-22）**：`validateSetArgs()` 对全部数值参数做范围校验（温度阈值 -20~120℃、PWM 频率 1~78125Hz、占空比 0~100%、喷雾时长 1~3600s、sprayPeriod 1~86400s、补水/排水超时、TDS 阈值 0~10000 等）与跨字段一致性校验（`fineL<fineH`、`minSparyTime<maxSparyTime`、各通道 `pwmNmin<pwmNmax`，跨字段以"新值优先、缺省取当前配置值"的有效值组合判断）——任一不合法返回 `errCode=-1` 及逐项错误消息，**不应用任何修改**；`waterTDSThreshold` 的 `----`/空串按"未修改"跳过（与赋值逻辑语义一致）
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
/setwifi?ssid=xxx&pwd=xxx&devicename=xxx&devicepwd=xxx&serverurl=xxx&sw1name=xxx&sw2name=xxx
```

设置后立即尝试连接，连接成功保存配置并在 10 秒后重启进入 normal 模式，可通过 `/scanap` 确认。
（2026-09-21 修复 F7：①必填参数校验——ssid/pwd/devicename/devicepwd/serverurl/sw1name/sw2name 缺失或为空时返回 `errCode=-1` 及缺失参数名列表，不再抛 KeyError 500；②日志脱敏——新增 `maskArgs()` 过滤 pwd/devicepwd/APPwd，`/setwifi`、`/reset`、`/restart` 的日志不再明文打印密码）

### 7.4 `/reset` — 恢复出厂

校验 `devicepwd` 后删除数据库中的 `systemConfig` 键并写入默认配置，5 秒后自动重启。
（2026-09-21 修复 F6：原实现误将 list 传给 `db.delete()`，导致接口抛异常、恢复出厂功能不可用）

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
main.py 主循环 (while True)
    │
    ├──► updateAliveTick() → 刷新主循环活性时间戳（Timer(0) 据此条件喂狗，见 5.1）
    │
    ├──► 依次调度 FSM（fsmList 遍历 run()）
    │       ├── AotomizerFSM.run() → 控制喷雾
    │       │       ├── 读 sensorData.fineTemp / humi / wetBulbTemp
    │       │       ├── 读空调霍尔状态（airConditionerStatus）
    │       │       ├── 读 config 配置引用（阈值、周期；参数设置后经 reloadConfig 生效）
    │       │       └── 写喷雾电磁阀 + 水泵
    │       └── WaterProcessFSM.run() → 控制进水/排水
    │               ├── 读 sensorData.waterMark
    │               ├── 读 sensorData.waterTankTDS（TDS 阈值判断）
    │               └── 写进水/废水电磁阀
    │
    ├──► tryNtpSync() → NTP 对时轮询（两阶段调度，见 13.1）
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
- STA 模式：连接指定 SSID（开机最长阻塞尝试 36s，失败转 AP 配网模式，配网模式 300s 后整机重启重试）
- AP 模式：热点 SSID 为 `{devicename}_{APIP}`（如 `Atomizer_192.168.4.1`），AP 侧 IP `192.168.4.1`，密码取 `APPwd`
- 自动重连机制（见 13.4）
- IP 广播（UDP 广播到 LAN；断线时 `getStationIP()` 返回 `None`，LED 转品红指示离线）

### 13.1 NTP 网络对时 (domain/ntpSync.py)（2026-09-21 新增）

**机制：**
- 主循环每轮调用 `tryNtpSync()`：STA 已连接时才动作
- **未同步**：每 60 秒重试一次，直到成功
- **已同步**：每 **1 周**（`NTP_RESYNC_INTERVAL_S = 7×24×3600`）自动重新校时一次，校准 RTC 晶振漂移；校时失败则 RTC 保持原值继续走时，等待下个 1 周周期
- `syncRtc()` 向 `ntp.aliyun.com:123` 发送 SNTP 请求（48 字节报文，超时 5s），取 UTC 秒数 + 8h（北京时间 UTC+8）写入 `machine.RTC()`
- **失败不改动 RTC**
- 对时成功前系统时间为 1970 起算的默认时间，日志时间戳无参考意义
- 实现细节（跳变安全两阶段设计）：以 `ntpSynced`（首次校时成功标记）切换阶段——成功前只做 60s 重试（节流基于 `ticks_ms` 单调节拍，不受跳变影响）；成功后标记才置 True 并启用 1 周周期判断，`ntpLastSync` 在首次成功（时间跳变完成后）才取样，因此系统时间跳变不会污染周期调度

**连带修复（重要）：** 开机运行时长原基于 `utime.time()` 差值计算——NTP 对时后系统时间向前跳变，会导致 `runTime`/`totalRunTime` 突变为巨大值。已改为 `utime.ticks_ms()` 节拍差计算，与墙钟时间完全解耦

### 13.2 全局日志体系 (domain/LogUtils.py)（2026-09-21 重构）

- 提供 `log(*args)`：输出 `[YYYY-MM-DD HH:MM:SS] 消息...`，时间来自系统时钟（NTP 对时后即为北京时间）
- 全项目自有代码（main.py、domain/、driver/ 共 9 个文件）的 `print()` 已全部替换为 `log()`；`lib/microdot.py` 第三方库保持原样
- 原 LogUtils 类（从未被使用）已删除

### 13.3 计时机制约定（2026-09-21 确立）

系统存在两类时间源，各司其职，**禁止混用**：

| 类别 | 时间源 | 特性 | 用途 |
|------|--------|------|------|
| **单调节拍** | `utime.ticks_ms()` + `ticks_diff` | 与墙钟无关；注意 `ticks_diff` 仅在真实差值 < 2^29ms（≈6.21 天）时保证正确（ticks_ms 以 2^30ms 回绕） | 一切**时长/超时/周期**判定 |
| **墙钟时间** | `utime.time()` / `utime.localtime()` / RTC | NTP 对时后为真实北京时间，但会被对时**跳变** | 日志时间戳、NTP 周期重校判断、对外展示 |

**单调节拍使用点：**

| 位置 | 变量 | 用途 |
|------|------|------|
| main.py 主循环 | `lastAliveTick` | 看门狗活性检测（30s 窗口，见 5.1） |
| main.py 主循环 | `lastSysTick` → `runMs` | 本次开机运行毫秒累计，输出时换算秒（/status 返回，见 7.1） |
| main.py sysTask | `lastSysTick` → `totalRunTimeMs` | 跨开机累计运行毫秒（DB 存秒），每小时落盘 |
| main.py 主循环 | `lastGcTick` / `lastLedTick` / `lastMainSaveTick` | GC 5min、LED 翻转 2s、落盘 1h——时间驱动定时任务（见 5.1） |
| AotomizerFSM | `lastRunTick` → `runTimeCounterMs`（逐轮累计） | 喷雾延时判定（spray1/2/3TimeOut、sprayPeriod，均 ms）与每小时统计落盘 |
| WaterProcessFSM | `lastRunTick` → `runTimeCounterMs`（逐轮累计） | 进水/排水超时、`minAddWaterInterval` 补水间隔判定（均 ms） |
| NTP 调度 | `ntpLastTryTick` | 首次校时成功前的 60s 重试节流（见 13.1） |
| main.py 主循环 | `lastWifiCheckTick`（30s） | WiFi 断线检查与复位式重连节流，normal 模式（见 13.4） |

**墙钟使用点：**

| 位置 | 用途 |
|------|------|
| LogUtils `log()` | 日志前缀 `[YYYY-MM-DD HH:MM:SS]`（对时成功前为 1970 起算的默认时间） |
| NTP 两阶段调度 | `ntpSynced` 置位后按 `utime.time() - ntpLastSync` 判断 1 周重校 |
| RTC | NTP 对时目标（北京时间 UTC+8，见 13.1） |

**时间驱动原则（2026-09-21 确立，随 FSM 提频至 10Hz 落地）：**
- 所有周期/定时行为必须基于"距上次 ≥ 阈值"的时间差判断，**禁止用轮询轮数取模**（`loopCounter % N`）——轮数驱动使定时行为与轮询频率耦合，提频后周期自动缩短且同秒重复触发（如原 `% 3600 == 0` 落盘在 10Hz 下同秒重复 10 次）
- FSM 轮询频率（10Hz）只影响**事件响应延迟**，不影响任何时长语义；配置项单位保持秒（用户可读），读取处统一 ×1000 转 ms
- **长寿命"距开机时长"值禁止对开机快照做差**（2026-09-22 补充）：`ticks_diff(now, bootTickMs)` 一旦真实间隔超过 2^29ms（≈6.21 天）即越窗变负——必须像 `runMs`/`runTimeCounterMs` 一样**逐轮累加每轮小间隔**；同理，任何秒级配置转 ms 的 ×1000 必须在 `__init__` 与 `reloadConfig()` 两处保持一致（202609220001 教训）

> **背景教训：** NTP 对时使 `utime.time()` 从"1970 起算的开机秒数"向前跳变约 17 亿秒，任何基于墙钟差值的时长判定都会被跳变破坏——runTime 突变巨大值（13.1 连带修复）、FSM 延时立即超时（202609210007 修复）均源于此。新代码凡涉及时长判定必须走单调节拍。

### 13.4 断线自动重连（2026-10-07 修订，版本 202610070001）

**背景：** 设备连续运行几十小时后（DHCP 租约到期 / 信标丢失 / 被 deauth / 路由器重启或信道切换），STA 可能进入"**接口仍 active 但内部关联-DHCP 状态机已卡死**"的假活状态。早期实现只在 `not wlan.active()` 时激活接口、随后对"热"接口反复 `wlan.connect()`——该调用只重发关联请求，不重走认证与 DHCP，无法从此类假死恢复，导致设备永久离线只能断电。

**机制（复位式重连，极简无状态）：**
- 主循环 normal 模式每 30s（`WIFI_RECONNECT_INTERVAL_MS`）检查 `wlan.isconnected()`，断线即调用一次 `wifi.startReconnect(ssid, pwd)`
- 每次调用都执行完整射频电源循环：`wlan.active(False)` → `sleep(1)` → `wlan.active(True)` → `wlan.connect(ssid, pwd)`，强制重走扫描→认证→关联→**DHCP** 全流程
- **无失败计数、无退避状态机**：30s 检查周期本身即天然退避，路由器恢复后最坏 30s 内重新上线
- `sleep(1)` 远小于喂狗 30s 活性窗口，不触发 WDT；全部异常捕获，返回 True/False
- 板端实测（2026-10-07，COM43，固件 v1.28.0）：函数耗时约 1023ms，STA active 正确经历 False→True；现场 SSID 不可达时设备按预期进入 AP 配网模式

---

## 14. 版本历史

| 版本号 | 日期 | 说明 |
|--------|------|------|
| 202606230001 | 2026-06-23 | 文档创建，记录基本架构 |
| 202606230002 | 2026-06-23 | 增加 PWM 参数映射错误说明，修复风扇用 pwm1 的问题 |
| 202606230003 | 2026-06-23 | 增加 DBUtils 新增方法说明、热插拔分析、I²C 通信距离 |
| 202606240000 | 2026-06-24 | **全量刷新**：纠正 PWM 引脚映射表（PWM1=Pin10水泵, PWM2=Pin46风扇电源, PWM3=Pin9风扇转速）；重写系统架构图；补充 TDS 异步状态机设计；增加无效值体系说明；完善前端架构描述；补充 runTime/waterTDSThreshold 等新增参数；更新传感器热插拔支持说明 |
| 202606250000 | 2026-06-25 | 二次重构 TDS 驱动为异步非阻塞（消除 Timer 回调中的 sleep）；修复 BMP280 get() 方法 var1==0 时未重置 T/P 的问题；修复 BMP280 getAltitude() 未检查无效压力；修复前端 nv() 函数处理 0.0 值；修正所有驱动在读取失败时立即置为 -9999 的行为 |
| 202609210000 | 2026-09-21 | **可靠性修复（深度分析 R1/R2/F6）**：R1 看门狗改为活性检测式喂狗——主循环每轮刷新 `lastAliveTick`，Timer(0) 回调仅在 30s 内有活性时喂狗，主循环卡死可触发 WDT 复位（原实现无条件喂狗，看门狗失效）；R2 DBUtils 增加模块级 `_thread` 锁，串行化 Web 线程与主线程的全部数据库操作，并改为 try/finally 保证异常时释放锁、关闭句柄（防 btree 并发损坏）；F6 修复 `/reset` 恢复出厂时 `db.delete()` 误传 list 导致接口 500 的问题 |
| 202609210001 | 2026-09-21 | **确定性 Bug 修复（深度分析 F10/F11/F7）**：F10 启动配置加载与出厂默认合并（`dict(默认)+update(存储值)`），老 mydb 缺少新增字段不再导致升级后启动 KeyError 变砖，DB 损坏时回退默认；F11 删除 AotomizerFSM 中复制残留的死方法 `checkWaterMark()`（引用不存在的 STATUS 枚举与未初始化属性）；F7 `/setwifi` 增加必填参数校验（缺失返回 errCode=-1 而非 500），新增 `maskArgs()` 日志脱敏，`/setwifi`、`/reset`、`/restart` 不再明文打印密码 |
| 202609210002 | 2026-09-21 | **功能修复（F1 + 喷雾时长算法）**：F1 启用第3路雾化电磁阀——`checkSpray2Timeout()` 恢复 `openPump()+openSparyEV3()`（原调用被注释导致 SPRAY_WATER_3 永远是1秒空过渡、EV3 从不动作），三路喷头轮流喷雾，各路时长一致；喷雾时长计算由阶梯式 if/elif 改为**线性+偏置**（fineLThreshold→minSparyTime，fineHThreshold→maxSparyTime，中间线性过渡、区间外钳位，配置异常时按最短时长兜底），`fineHThreshold` 由此参与控制 |
| 202609210003 | 2026-09-21 | 喷雾时长算法定稿：线性+偏置计算基准时长，三路喷头不均分，按阀门安装位置（上→下=1/2/3）配比递减——阀门1=100%、阀门2=70%、阀门3=40%，不足 1 秒按 1 秒兜底 |
| 202609210004 | 2026-09-21 | **新增 NTP 对时 + 全局日志时间戳**：新增 domain/ntpSync.py——WiFi 联网后从 ntp.aliyun.com 获取 UTC 时间写入 RTC（北京时间 UTC+8），失败不改动 RTC、每 60s 重试直到成功一次；LogUtils 重构为 `log()` 全局函数，全项目 print 输出统一带 `[日期 时间]` 前缀（microdot 除外）；连带修复 runTime/totalRunTime 隐患——改用 ticks_ms 节拍差计算，避免 NTP 对时跳变导致运行时长突变为巨大值 |
| 202609210005 | 2026-09-21 | NTP 周期校时（两阶段设计）：由"成功一次后永久停止"改为"未同步每 60s 重试，首次成功后每 1 周自动重新校时"（校准 RTC 晶振漂移）；以 `ntpSynced` 首次成功标记切换阶段——60s 节流用 ticks_ms 单调节拍、1 周周期的 `ntpLastSync` 仅在首次成功（时间跳变完成后）取样，结构上消除系统时间跳变对调度的影响 |
| 202609210006 | 2026-09-21 | **文档全量一致性刷新（无代码改动）**：5.3 喷雾逻辑重写为与代码一致（空调开 + 翅片温度 > fineLThreshold 触发、线性+偏置基准时长、三路 100%/70%/40% 配比），修正原"fineHThreshold+湿度"过期描述；FSM 入口方法名由 tick() 更正为 run()（5.1/5.3/9.3）；主循环职责与 9.3 数据流补充 tryNtpSync()；修正 TDS UART 波特率 38400→9600bps（bsp 实例化未传 baudrate，取驱动默认值，与 3.1/6.3 两处）；4.2 模块职责表补充 ntpSync/LogUtils；1.2 核心特性补充 NTP 对时与全局日志时间戳；重写 15 节 Known Issues 为当前真实遗留问题清单，并新增记录 FSM 墙钟节拍隐患（runTimeCounter 基于 utime.time()，NTP 跳变影响喷雾延时判定，见 15 节 #6） |
| 202609210007 | 2026-09-21 | **修复 FSM 墙钟节拍隐患（NTP 跳变连带，15 节原 #6）**：AotomizerFSM 与 WaterProcessFSM 的 `runTimeCounter` 原基于墙钟 `utime.time()`——NTP 对时使系统时间向前跳变后，喷雾延时/进水超时/排水超时/补水间隔判定与 `% 3600` 统计落盘周期全部紊乱；改为开机以来的单调秒数（`bootTickMs = utime.ticks_ms()` + `ticks_diff(...) // 1000`，与 main.py runTime 修复同模式），两个 FSM 的全部差值比较逻辑无需改动即恢复正确，编号 #6 从 Known Issues 移除；同步更新文档——新增 13.3 节「计时机制约定」集中说明单调节拍与墙钟的分工，5.4 补水/排水逻辑标注计时来源，7.1 runTime 说明补充 FSM 一致性 |
| 202609210008 | 2026-09-21 | **修复 runTime/totalRunTime 两个边界 bug（NTP 临界检查发现）**：NTP 对时本身不影响二者（RTC 跳变不动 ticks 时基，Web 线程并发读也安全），但发现：① `runTime` 原 = `ticks_diff(now, bootTickMs)//1000`——差值即开机时长，超过 `ticks_diff` 安全窗口（2^29ms ≈ 6.21 天）后变负数，12.42 天回绕后重新计数（长期运行呈锯齿错误）；② `totalRunTime` 每轮 `//1000` 整除丢弃毫秒余数且每轮刷新起点，长期累计偏慢 2~9%。改为**毫秒级累计式**：主循环每轮对 `runMs`/`totalRunTimeMs` 精确累加 `ticks_diff`（每轮间隔约 1s，恒在安全窗口内），`/status` 输出与落盘时才 `//1000` 换算秒——DB 存储格式不变（秒字符串），老数据兼容；13.3 节同步修正安全窗口表述 |
| 202609210009 | 2026-09-21 | 小修两处：① 修正 AotomizerFSM 水不可用日志拼写 `Water inavailable` → `Water unavailable`；② bsp.py 实例化 TDS 时显式传入 `baudrate=9600`（此前依赖驱动默认值 9600 隐式生效，行为不变，显式化防驱动默认值变更导致波特率静默漂移）；6.3 节括号注释同步更新 |
| 202609210010 | 2026-09-21 | **FSM 提频至 10Hz + 时间驱动解耦**：主循环周期 1s → 100ms（`sleep_ms(100)`），FSM 事件响应延迟平均 0.5s → 50ms；全部定时逻辑由"轮数取模"改为**真实时间判断**（RTC 时基 ticks_ms 单调读数，`ticks_diff >= 阈值`）——main.py 的 GC 5min/LED 2s/落盘 1h、两个 FSM 的每小时统计落盘均改为时间边沿触发（原 `% 3600 == 0` 在 10Hz 下同秒重复落盘 10 次）；两个 FSM 内部计时转毫秒（`runTimeCounterMs`，spray1/2/3TimeOut、sprayPeriod、waterFill/DischargeTimeOut、minAddWaterInterval 读取处 ×1000，config 单位不变），喷雾时长控制精度 ±1s → ±0.1s；状态日志按时间节流每 1s 一次防 10Hz 刷屏；删除仅赋值未使用的 `lastOverTempTime`；`loopCounter` 退役为日志序号；13.3 节新增「时间驱动原则」；传感器采集保持 Timer(1) 1s 周期不变 |
| 202609210011 | 2026-09-21 | **修复 PWM 参数变更内存泄漏（bsp.setConfig 重复重建硬件对象）**：原 `setConfig()` 每次调用都执行 `initHW()` 重建 3 个 PWM 对象——Web 端每次保存参数（/status?mode=set）都触发一轮"构造-丢弃"，累积待 GC 的 PWM 对象与硬件通道重绑定开销，且设备运行中（如正在喷雾/风扇转动时）重建会让 PWM 输出瞬间毛刺；改为 PWM 对象仅首次构造（`_pwmReady` 标志），参数变更走新增的 `updatePWM()` 原地更新 `freq()/duty()`；同步排查其余内存面（Timer 硬件 id 复用覆盖语义、DBUtils 线程锁+closeDB、TDS bytearray 复用、sensorData 固定标量字段）均无泄漏；3.3 节同步更新 |
| 202609220001 | 2026-09-22 | **全项目审查后修复 4 项（P0×2 + P1×2）**：① P0-1 reloadConfig 单位回归——AotomizerFSM `sprayPeriod` 与 WaterProcessFSM `minAddWaterInterval/waterFillTimeOut/waterDischargeTimeOut` 共 4 处补回 `×1000`（原 Web 保存任意配置后 sprayPeriod 变 40ms 致近乎连续喷雾、排水/进水阀 60ms/850ms 高频空转循环）；② P0-2 FSM 节拍越窗——两 FSM `runTimeCounterMs` 原基于 `ticks_diff(now, bootTickMs)`，连续运行超 6.21 天后变负（状态日志/每小时落盘停摆、极端时序下喷雾/排水超时永不触发致执行器卡死），改为 run() 内逐轮累加 `lastRunTick` 小间隔（与 main.py runMs 同模式），13.3 补充"长寿命距开机值禁止对开机快照做差"原则；③ P1-4 `wifi.getStationIP()` 失败由返回错误字符串改为返回 `None`（原被 truthy 误判为有效 IP，断线时以非法超长 SSID 反复启 AP、LED 误报在线），/setwifi 返回值兜底空串；④ P1-7 新增 WiFi 断线应用层重连——wifi.py 新增 `startReconnect()`（wlan.connect 异步非阻塞），主循环 normal 模式每 30s 时间驱动检查 `isConnected()`、断线即发起重连，不影响 10Hz 节拍与喂狗 |
| 202609220002 | 2026-09-22 | **审查后修复 3 项（P1×2 + R4）**：① P1-8 防空水箱干转——AotomizerFSM 原只查 TDS 水质不查水位，水箱空时仍照常喷雾致水泵干转；`readSystemSensor()` 每轮刷新 `waterMark`（bsp.getWaterTankStatus），`checkOverTemperature()` 增加 `waterMark == EMPTY` 前置拦截（回 READY、日志告警），等待 WaterProcessFSM 补水；② P1-5 保存配置打断喷雾——`bsp.updatePWM()` 原无条件把泵 duty 强制回 `pwm1default`(0)，运行中保存任意配置即致当前喷雾相位静默停泵；改为跳过泵（泵由 FSM 独占控制），pwm1 参数变更下次上电生效；③ R4 参数校验——`main.py` 新增 `validateSetArgs()`，`/status?mode=set` 先整体校验后应用：数值范围（温度阈值/PWM 频率占空比/喷雾与补水时长/TDS 阈值/Modbus）+ 跨字段一致性（`fineL<fineH`、`minSparyTime<maxSparyTime`、`pwmNmin<pwmNmax`，有效值组合兼容部分更新）+ NaN/非数字防御，任一不合法返回 `errCode=-1` 与逐项错误、不应用任何修改（15 节 R4 行删除） |
| 202609220003 | 2026-09-22 | **F4 业务决策落地（仅文档修正，无代码变更）**：确认当前无换水硬件，TDS 超阈值不做换水——代码复核证实 WaterProcessFSM 排水/进水循环仅由水位 `waterMark` 触发（`waterTDSThreshold` 仅加载与显示，从未参与控制），TDS 阈值唯一作用是 AotomizerFSM 喷雾水质门控（≥ 阈值禁止喷雾）；修正文档两处错误描述（2.2 配置表"超过则排水"、5.4"当 TDS 超过阈值→自动排水补水"），15 节 F4 行删除 |
| 202609220004 | 2026-09-22 | **复审后修复前端 2 项（FE-1/FE-9）**：① FE-1 契约断裂——`handleResponse()` 原把 `errCode='-1'` 硬编码为"密码错误!"且预置文案优先，R4 校验拒绝返回的具体原因（msg）被丢弃误导用户；改为失败时服务端 `msg` 优先（无 msg 才回退预置文案），成功时仍保留预置中文文案，单点修复覆盖全部 5 个保存入口；② FE-9 无效温度误着色——模型层无效值为数字 -9999（`nv(v, invalid)`），视图判断 `!== '----'` 恒真致 -9999 被染成正常绿色；着色条件补充 `!== INVALID_VALUE` 排除。前端其余发现（SSID XSS、-9999 真值误判"可用"、轮询无超时、编辑被覆盖、URL 未编码等）为已知建议级事项 |
| 202609220005 | 2026-09-22 | **无效值体系专项检查后修复 2 项（BE-1/BE-2）**：① BE-1——两个 FSM 的传感器显示副本（AotomizerFSM `finTemp/humity/wetBulbTemp`、WaterProcessFSM `inWaterTDS/inWaterTemp/waterTankTDS/waterTankTemp`）初始化为 0，违反"失败值必须立即置 -9999"硬约束，开机后首个 run() tick（<100ms）内 Web 查询会显示看似有效的 0 读数；改为 init -9999；② BE-2——`bsp._applyTdsResult()` 失败时打出 `-999.9 ℃, -9999.0 ppm` 噪声日志；改为双通道失败合并单条 WARN、单通道失败仅 WARN 失败通道、正常通道保持完整日志。检查同时确认：sensorData 17 字段/-9999 驱动失败路径/AACOps 湿球入口保护/getWaterAvailableStatus 判断/JSON 透传均健康，int 与 float 型 -9999 在 `==` 与 JSON 序列化下等价无害 |
| 202610070001 | 2026-10-07 | **修复长跑几十小时后 WiFi 掉线不可恢复**：原 `startReconnect()` 仅在 `not wlan.active()` 时 active(True)，随后对仍 active 的"热"接口反复 `connect()`；长跑后（DHCP 租约到期/信标丢失/deauth/路由重启）STA 会进入"接口 active 但关联-DHCP 状态机卡死"的假活状态，热 connect 只重发关联请求、无法恢复，设备永久离线。改为**复位式重连**：每次调用执行 `active(False)` → `sleep(1)` → `active(True)` → `connect()` 完整射频电源循环，强制重走扫描→认证→关联→DHCP；主循环 30s 检查周期不变（天然退避，无需失败计数），1s 复位延时远小于喂狗 30s 活性窗口，异常全捕获。NTP socket（finally close）、ticks_ms 节流（无 NTP 跳变问题）、非阻塞喂狗均已复核无泄漏。**当日烧录 COM43 板端验证**：21 源码+5 静态资源经 mpremote 上传；启动流程正常（BSP/传感器/FSM/Web 均 OK），开机 WiFi 阻塞约 36s 超时后按设计进入 AP 配网模式（现场 SSID 不可达），条件喂狗日志正确；板端直接调用 `startReconnect()` 实测耗时约 1023ms、active 经历 False→True 后恢复 True。板载固件确认为 **v1.28.0（2026-04-06）**，1.3 节固件版本同步更新；端到端"关路由→30s 重连→开路由→恢复"需现场有 AP 时由用户复验 |

---

## 15. 待办事项 / Known Issues

（编号 F/R 引用自 2026-09-21 深度分析报告，便于追溯；已修复项见 14 节版本历史）

**必修（功能正确性）：**

| # | 描述 | 优先级 |
|---|------|--------|
| 1 | F2+R7 安全开关未接入：BSP 已提供 `isSysEnabled()/isSprayEnabled()`，但 FSM 从未调用——系统使能断开时设备仍会喷雾（需先确认断开时正在喷雾的处理语义） | 高 |
| 2 | F5 双 FSM 互斥：AotomizerFSM 与 WaterProcessFSM 可能同时操作电磁阀/水泵，冲突时序未定义 | 高 |
| 5 | F3 湿度/湿球温度未参与喷雾控制（已采集并显示，控制仅用翅片温度） | 中 |

**健壮性（建议）：**

| # | 描述 | 优先级 |
|---|------|--------|
| 7 | R5 水位传感器读取无防抖/滤波，临界水位抖动可能误触补水 | 中 |
| 8 | R6 BMP280 温度/气压/海拔分三次接口调用，各自独立触发 `get()`，同一周期内重复 I²C 读取 | 低 |
| 9 | R3 BMP280/HDC1080 的 I²C 同步读取仍在 Timer(1) 回调中执行，总线异常时可能阻塞回调（TDS 已异步化） | 低 |
| 10 | R10 统计数据周期性落盘存在 Flash 写入磨损 | 低 |
| 11 | R12 广播 AP 常开：配网完成后 AP 未关闭，持续占用射频 | 低 |
| 18 | P1-6 正常模式调用 `/setwifi` 测试新 SSID 失败会短暂断开现有连接；202610070001 后已被主循环 30s 复位式重连兜底（若新凭据本身错误则仍无法连回旧 SSID，该接口建议仅在配网模式使用） | 低 |

**低优先级：**

| # | 描述 | 优先级 |
|---|------|--------|
| 12 | PWM4 通道硬件未接线，配置参数保留但无物理作用 | 低 |
| 13 | boot.py 当前为空，可考虑启用 WebREPL | 低 |
| 14 | HDC1080 无硬件 CRC 校验，数据正确性依赖 I²C ACK（见 6.2） | 中 |
| 15 | BMP280 和 HDC1080 共用同一组 I²C 引脚，热插拔会相互影响 | 中 |
| 16 | `/status` 参数类型转换逻辑较分散，可考虑表驱动统一封装 | 低 |
| 17 | 无 OTA 更新能力 | 低 |
