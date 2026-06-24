# Aotomizer4ESP32S3 系统设计文档

## 1. 项目概述

### 1.1 项目名称
Aotomizer4ESP32S3 - 空调外机智能喷雾降温控制系统

### 1.2 项目目标
基于 ESP32-S3 微控制器，实现空调外机散热器翅片的智能喷雾降温控制，通过监测温度自动触发喷雾降温，延长空调使用寿命、提高制冷效率。

### 1.3 技术栈
- **硬件平台**: ESP32-S3 (支持 SPIRAM_OCT)
- **固件版本**: ESP32_GENERIC_S3-SPIRAM_OCT-20250415-v1.25.0.bin
- **开发语言**: MicroPython
- **Web框架**: Microdot
- **前端框架**: Spectre CSS + jQuery + Chart.js

### 1.4 软件版本
当前版本: `202606240000`

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         应用层 (Application)                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   Web Server    │  │  状态机管理     │  │  WiFi管理       │  │
│  │  (Microdot)     │  │ (FSM Manager)   │  │  (WiFi Module)  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                         业务逻辑层 (Domain)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ AotomizerFSM    │  │ WaterProcessFSM │  │   DBUtils       │  │
│  │ (喷雾状态机)     │  │ (水处理状态机)   │  │  (数据存储)     │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   SensorData    │  │    AACOps       │  │   fileUtils     │  │
│  │  (传感器数据)    │  │  (湿球温度计算)  │  │  (文件工具)     │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                         硬件驱动层 (Driver)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │     BSP         │  │    BMP280       │  │    HDC1080      │  │
│  │ (板级支持包)     │  │ (气压传感器)     │  │ (温湿度传感器)  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐                        │
│  │     enum        │  │     TDS         │                        │
│  │  (枚举定义)      │  │ (TDS传感器驱动) │                        │
│  └─────────────────┘  └─────────────────┘                        │
├─────────────────────────────────────────────────────────────────┤
│                         第三方库层 (Lib)                          │
│  ┌─────────────────┐                                              │
│  │   Microdot      │                                              │
│  │  (Web框架)       │                                              │
│  └─────────────────┘                                              │
├─────────────────────────────────────────────────────────────────┤
│                         前端资源层 (Static)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   index.html    │  │   Chart.js      │  │   Spectre CSS   │  │
│  │  (控制界面)      │  │  (图表库)        │  │  (样式库)       │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
Aotomizer4ESP32S3/
├── boot.py                 # MicroPython 启动文件
├── main.py                 # 主程序入口
├── driver/                 # 硬件驱动层
│   ├── bsp.py              # 板级支持包 (单例模式)
│   ├── bmp280.py           # BMP280 气压/温度传感器驱动
│   ├── hdc1080.py          # HDC1080 温湿度传感器驱动
│   ├── enum.py             # 系统枚举定义
│   └── tds.py              # TDS传感器驱动 (串口通信)
├── domain/                 # 业务逻辑层
│   ├── AotomizerFSM.py     # 雾化器状态机
│   ├── WaterProcessFSM.py  # 水处理状态机
│   ├── wifi.py             # WiFi 连接管理
│   ├── DBUtils.py          # BTree 数据库工具
│   ├── sensorData.py       # 传感器数据封装类
│   ├── AACOps.py           # 湿球温度计算 (空调焓湿图算法)
│   ├── fileUtils.py        # 文件操作工具
│   ├── cfgManager.py       # 配置文件管理
│   └── LogUtils.py         # 日志工具类
├── lib/                    # 第三方库
│   └── microdot.py         # Microdot Web 框架 (已修复UTF-8解码)
├── static/                 # Web 前端资源
│   ├── index.html          # 控制界面主页 (模块化架构)
│   ├── chart.umd.js        # Chart.js 图表库
│   ├── jquery.min.js       # jQuery 库
│   ├── spectre.min.css     # Spectre CSS 框架
│   ├── sweetalert.min.js   # SweetAlert 弹窗库
│   └── favicon.ico         # 网站图标
├── Doc/                    # 文档目录
│   └── DESIGN.md           # 系统设计文档
├── .gitignore              # Git 忽略配置
└── README.md               # 项目说明
```

---

## 3. 硬件接口设计

### 3.1 ESP32-S3 引脚分配

| 引脚号 | 功能 | 类型 | 说明 |
|--------|------|------|------|
| 3 | I2C SCL | 软件I2C | 传感器时钟线 |
| 8 | I2C SDA | 软件I2C | 传感器数据线 |
| 48 | WS2812 | 输出 | LED状态指示灯 |
| 46 | PWM1 | 输出 | 风扇PWM控制1 |
| 9 | PWM2 | 输出 | 风扇PWM控制2 |
| 10 | PWM3 | 输出 | 水泵PWM控制 |
| 11 | GPIO | 输出 | 雾化电磁阀1 (sprayEV1) |
| 12 | GPIO | 输出 | 雾化电磁阀2 (sprayEV2) |
| 13 | GPIO | 输出 | 雾化电磁阀3 (sprayEV3) |
| 14 | GPIO | 输出 | 进水电磁阀 (waterInEV) |
| 21 | GPIO | 输出 | 废水电磁阀 (wasteWaterEV) |
| 15 | GPIO | 输入(PULL_UP) | 水箱高水位传感器 |
| 16 | GPIO | 输入(PULL_UP) | 水箱低水位传感器 |
| 4 | GPIO | 输入(PULL_DOWN) | 系统使能开关 |
| 5 | GPIO | 输入(PULL_DOWN) | 喷雾使能开关 |
| 6 | GPIO | 输入(PULL_DOWN) | 空调强制使能 |
| 7 | GPIO | 输入(PULL_DOWN) | 空调霍尔传感器 (检测空调运行状态) |
| 17 | UART1 RX | 输入 | TDS传感器接收 |
| 18 | UART1 TX | 输出 | TDS传感器发送 |

### 3.2 I2C 传感器

| 传感器 | I2C地址 | 功能 | 测量参数 |
|--------|---------|------|----------|
| HDC1080 | 0x40 | 温湿度传感器 | 温度(-40~125℃)、湿度(0~100%) |
| BMP280 | 0x76 | 气压传感器 | 温度、气压、海拔 |

### 3.3 TDS 传感器

| 参数 | 值 | 说明 |
|------|-----|------|
| UART端口 | UART1 | 串口通信 |
| TX引脚 | GPIO18 | ESP32发送 |
| RX引脚 | GPIO17 | ESP32接收 |
| 波特率 | 9600 | 固定波特率 |
| 帧格式 | 11字节 | HEAD+LEN+CMD+CH+COND(2)+TEMP(2)+DATA(2)+CS(1) |

### 3.4 硬件资源使用情况

| 硬件类别 | 硬件名称 | 引脚/端口 | 使用状态 | 用途描述 |
|----------|----------|-----------|----------|----------|
| **GPIO输出** | 雾化电磁阀1 | GPIO11 | 使用中 | 控制第一个喷雾头电磁阀开关 |
| **GPIO输出** | 雾化电磁阀2 | GPIO12 | 使用中 | 控制第二个喷雾头电磁阀开关 |
| **GPIO输出** | 雾化电磁阀3 | GPIO13 | 使用中 | 控制第三个喷雾头电磁阀开关 |
| **GPIO输出** | 进水电磁阀 | GPIO14 | 使用中 | 控制水箱进水电磁阀 |
| **GPIO输出** | 废水电磁阀 | GPIO21 | 使用中 | 控制水箱排水电磁阀 |
| **GPIO输出** | WS2812 LED | GPIO48 | 使用中 | 系统状态指示LED灯 |
| **GPIO输入** | 水箱高水位传感器 | GPIO15(PULL_UP) | 使用中 | 检测水箱是否满水 |
| **GPIO输入** | 水箱低水位传感器 | GPIO16(PULL_UP) | 使用中 | 检测水箱是否缺水 |
| **GPIO输入** | 系统使能开关 | GPIO4(PULL_DOWN) | 使用中 | 系统总开关控制 |
| **GPIO输入** | 喷雾使能开关 | GPIO5(PULL_DOWN) | 使用中 | 喷雾功能使能控制 |
| **GPIO输入** | 空调强制使能 | GPIO6(PULL_DOWN) | 使用中 | 空调强制运行控制 |
| **GPIO输入** | 空调霍尔传感器 | GPIO7(PULL_DOWN) | 使用中 | 检测空调运行状态 |
| **PWM输出** | 风扇电源控制 | GPIO46 (PWM2) | 使用中 | MOS管电源控制，风扇开关 |
| **PWM输出** | 风扇转速控制 | GPIO9 (PWM3) | 使用中 | 风扇转速调节 |
| **PWM输出** | 水泵控制 | GPIO10 (PWM1) | 使用中 | 水泵转速调节 |
| **PWM输出** | PWM通道4 | GPIO预留 | 可用 | 预留扩展，可用于额外风扇或水泵 |
| **UART** | UART1 | GPIO17(RX)/GPIO18(TX) | 使用中 | TDS传感器串口通信 |
| **UART** | UART0 | GPIO默认 | 可用 | 预留扩展，可用于调试或其他串口设备 |
| **I2C** | 软件I2C | GPIO3(SCL)/GPIO8(SDA) | 使用中 | 连接BMP280和HDC1080传感器 |
| **I2C传感器** | BMP280 | 0x76 | 使用中 | 气压/温度/海拔传感器 |
| **I2C传感器** | HDC1080 | 0x40 | 使用中 | 温湿度传感器 |
| **串口传感器** | TDS传感器 | UART1 | 使用中 | 双通道TDS水质检测（进水+水箱） |
| **定时器** | Timer(1) | - | 使用中 | 传感器数据采集定时触发（1秒周期） |
| **定时器** | Timer(0/2/3) | - | 可用 | 预留扩展，可用于其他定时任务 |
| **ADC** | ADC通道 | - | 可用 | 预留扩展，可用于模拟量传感器 |
| **SPI** | SPI总线 | - | 可用 | 预留扩展，可用于SD卡或其他SPI设备 |
| **WiFi** | WiFi模块 | - | 使用中 | 无线网络连接、AP模式配置 |
| **看门狗** | WDT | - | 使用中 | 系统看门狗，60秒超时保护 |

### 3.5 执行器控制

#### 3.5.1 电磁阀控制
```python
class EV:
    WATER_INPUT_EV = 1    # 进水电磁阀
    WASTE_WATER_EV = 2    # 废水电磁阀
    WATER_SPRAY_EV_1 = 3  # 喷雾电磁阀1
    WATER_SPRAY_EV_2 = 4  # 喷雾电磁阀2
    WATER_SPRAY_EV_3 = 5  # 喷雾电磁阀3

class Switch:
    OFF = 0
    ON = 1
```

#### 3.4.2 PWM 控制 (4通道)
| 通道 | 默认频率 | 默认占空比范围 | 用途 |
|------|----------|----------------|------|
| PWM1 | 25000Hz | 15%~100% | 风扇控制1 |
| PWM2 | 25000Hz | 15%~100% | 风扇控制2 |
| PWM3 | 25000Hz | 15%~100% | 水泵控制 |
| PWM4 | 25000Hz | 15%~100% | 预留 |

#### 3.4.3 水位传感器

```python
class WaterMark:
    EMPTY = 1   # 水箱空 (低水位传感器高电平)
    NORMAL = 2  # 水箱正常 (高水位低,低水位低)
    FULL = 3    # 水箱满 (高水位传感器高电平)
```

检测逻辑:
- 高水位传感器=1 → 水箱满
- 高水位=0, 低水位=0 → 水箱正常
- 高水位=0, 低水位=1 → 水箱空

---

## 4. 核心模块详细设计

### 4.1 BSP (板级支持包)

**文件**: [driver/bsp.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\driver\bsp.py)

**设计模式**: 单例模式 (Singleton)

**主要功能**:
1. 硬件初始化 (I2C、PWM、GPIO、传感器)
2. 传感器数据采集 (定时器驱动)
3. 执行器控制 (电磁阀、水泵、风扇)
4. 状态指示 (WS2812 LED)

**关键方法**:

| 方法 | 功能 | 参数 |
|------|------|------|
| `setConfig(config)` | 设置系统配置 | JSON配置对象 |
| `setLEDArray(color)` | 设置LED颜色 | (R,G,B)元组 |
| `setFan1Pwm(percent)` | 设置风扇PWM | 0-100百分比 |
| `setEV(ev, status)` | 控制电磁阀 | EV枚举, Switch枚举 |
| `setWaterPump(percent)` | 控制水泵 | 0-100百分比 |
| `getWaterTankStatus()` | 获取水位状态 | 返回WaterMark枚举 |
| `getSensorData()` | 获取传感器数据 | 返回SensorData对象 |
| `getAirconditionerStatus()` | 获取空调状态 | 返回Switch枚举 |
| `getWaterAvailableStatus()` | 获取供水状态 | 返回bool |

**传感器数据采集**:
- 使用 Timer(1) 定时器，周期1000ms
- 定时读取 HDC1080 温湿度
- 定时读取 BMP280 气压/海拔
- 定时读取 TDS 传感器数据 (双通道)
- 计算湿球温度 (AACOps算法)

### 4.2 AotomizerFSM (雾化器状态机)

**文件**: [domain/AotomizerFSM.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\AotomizerFSM.py)

**状态定义**:

```python
class STATUS:
    INIT = 0              # 初始化状态
    READY = 1             # 就绪状态
    AIR_CONDITIONER_ON = 2 # 空调运行状态
    OVER_TEMP = 3         # 过温状态
    SPRAY_WATER_1 = 4     # 喷雾阶段1
    SPRAY_WATER_2 = 5     # 喷雾阶段2
    SPRAY_WATER_3 = 6     # 喷雾阶段3
    SPRAY_DELAY = 7       # 喷雾间隔等待
```

**状态转换图**:

```
INIT → READY → AIR_CONDITIONER_ON → OVER_TEMP → SPRAY_WATER_1 → SPRAY_WATER_2 → SPRAY_WATER_3 → SPRAY_DELAY → READY
         ↑                                                                                              │
         └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**状态处理逻辑**:

| 状态 | 处理函数 | 触发条件 | 动作 |
|------|----------|----------|------|
| INIT | `initDevice()` | 启动时 | 关闭所有执行器，转到READY |
| READY | `checkAirConditionerStatus()` | 空调运行 | 检测空调霍尔传感器状态 |
| AIR_CONDITIONER_ON | `checkOverTemperature()` | 温度>阈值 | 监测翅片温度 |
| OVER_TEMP | `overTemp()` | 温度超限 | 开启水泵+喷雾阀1 |
| SPRAY_WATER_1 | `checkSpray1Timeout()` | 喷雾时间到 | 切换到喷雾阀2 |
| SPRAY_WATER_2 | `checkSpray2Timeout()` | 喷雾时间到 | 关闭所有阀，转SPRAY_DELAY |
| SPRAY_DELAY | `checkSprayDelayTimeout()` | 周期时间到 | 返回READY |

**喷雾时间计算**:
```python
extra = max(0, finTemp - 38)
sprayTime = min(self.minSparyTime + extra, self.maxSparyTime)
```

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| fineLThreshold | 31.5℃ | 喷雾启动温度阈值 |
| fineHThreshold | 36.0℃ | 喷雾停止温度阈值 |
| sprayPeriod | 40s | 喷雾周期 |
| minSparyTime | 5s | 最小喷雾时间 |
| maxSparyTime | 12s | 最大喷雾时间 |
| pwm1freq | 25000Hz | PWM频率 |
| pwm1min | 15% | PWM最小占空比 |
| pwm1max | 100% | PWM最大占空比 |

### 4.3 WaterProcessFSM (水处理状态机)

**文件**: [domain/WaterProcessFSM.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\WaterProcessFSM.py)

**状态定义**:

```python
class STATUS:
    INIT = 0              # 初始化状态
    READY = 1             # 就绪状态
    WATER_TANK_OK = 2     # 水箱水位正常
    WATER_TANK_NOT_OK = 3 # 水箱水位异常
    WATER_DISCHARGE_OK = 4 # 排水完成
```

**状态转换图**:

```
INIT → READY → WATER_TANK_OK → READY
         │
         ↓ (水位异常)
    WATER_TANK_NOT_OK → WATER_DISCHARGE_OK → (补水) → READY
```

**水处理流程**:

1. **水位检测**: 检测高/低水位传感器状态
2. **排水阶段**: 水位异常时，排废水60秒
3. **补水阶段**: 排水完成后，开启进水阀补水
4. **补水完成**: 水位满或超时850秒，关闭进水阀

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| waterFillTimeOut | 850s | 补水超时时间 |
| waterDischargeTimeOut | 60s | 排水时间 |
| minAddWaterInterval | 2400s | 最小补水间隔 |
| waterTDSThreshold | 15ppm | TDS阈值（水箱TDS超过此值时排水） |

**状态反馈参数**:

| 参数 | 说明 |
|------|------|
| totalAddWaterCount | 总补水次数 |
| waterMark | 水位状态（1=空、2=正常、3=满） |
| inWaterTDS | 进水TDS值 |
| inWaterTemp | 进水水温 |
| waterTankTDS | 水箱TDS值 |
| waterTankTemp | 水箱水温 |
| waterAvailable | 供水状态（可用/不可用） |
| waterTDSThreshold | TDS阈值 |

### 4.4 SensorData (传感器数据封装)

**文件**: [domain/sensorData.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\sensorData.py)

**数据字段**:

| 字段 | 默认值 | 说明 |
|------|--------|------|
| temp | -9999 | 温度 |
| humi | -9999 | 湿度 |
| wetBulbTemp | -9999 | 湿球温度 |
| presure | -9999 | 气压 |
| altitude | -9999 | 海拔 |
| luminance | -9999 | 光照度 |
| pm25 | -9999 | PM2.5 |
| tempBMP280 | -9999 | BMP280温度 |
| tempLM75_1/2/3 | -9999 | LM75温度 |
| inWaterTDS | -9999 | 进水TDS |
| inWaterTemp | -9999 | 进水水温 |
| waterTankTDS | -9999 | 水箱TDS |
| waterTankTemp | -9999 | 水箱水温 |

**设计特点**:
- 使用 property 封装，便于外部访问
- `__dict__` 方法返回所有数据字典，方便JSON序列化

### 4.5 AACOps (湿球温度计算)

**文件**: [domain/AACOps.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\AACOps.py)

**算法原理**:
基于空调焓湿图计算湿球温度，用于评估空气冷却效率。

**核心公式**:
- 饱和水汽压: `E(t) = 611.2 * exp(17.67*t/(243.5+t))`
- 干空气比焓: `g(t) = 1.01*t`
- 水蒸气比焓: `v(t) = 2501 + 1.85*t`
- 含湿量: `d(t,rh) = 0.622*rh*E(t)/(p-rh*E(t))`
- 湿空气比焓: `h(t,rh) = g(t) + d(t,rh)*v(t)`

**优化策略**:
1. 预计算不随湿球温度变化的常量
2. 内联计算消除重复函数调用
3. 二分法搜索替代线性搜索 (100-300倍性能提升)
4. 可选牛顿迭代法 (5-10次迭代收敛)

### 4.6 DBUtils (数据存储)

**文件**: [domain/DBUtils.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\DBUtils.py)

**存储方式**: BTree 数据库 (MicroPython内置)

**数据库文件**: `mydb`

**主要方法**:

| 方法 | 功能 |
|------|------|
| `save(kv)` | 保存键值对 |
| `get(k)` | 获取单个值 |
| `multiGet(keys)` | 批量获取多个值 |
| `getAll()` | 获取所有数据 |
| `openDB()` | 打开数据库 |
| `closeDB()` | 关闭数据库 |

**存储数据**:
- systemConfig: 系统配置
- totalRunTime: 总运行时间
- totalSprayCount: 总喷雾次数
- totalAddWaterCount: 总补水次数

**注意**: DBUtil仅支持字符串存储，读取时需根据实际需要转换为对应类型。

### 4.7 WiFi 模块

**文件**: [domain/wifi.py](file:///d:\develop\ESP32\Aotomizer4ESP32S3\domain\wifi.py)

**功能**:
1. WiFi Station 模式连接
2. WiFi AP 模式配置
3. WiFi 扫描
4. 连接状态检测

**主要方法**:

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `connectToWifi(ssid, pwd)` | 连接WiFi | True/False |
| `testWifiConnect(ssid, pwd)` | 测试WiFi连接 | True/False |
| `startAP(apname, appwd)` | 启动AP模式 | True/False |
| `stopAP()` | 关闭AP模式 | True/False |
| `scanAP()` | 扫描WiFi | {ssid: RSSI} |
| `isConnected()` | 检查连接状态 | True/False |
| `getStationIP()` | 获取Station IP | IP字符串 |

**连接超时**: 35秒

---

## 5. Web API 设计

### 5.1 API 接口列表

| 接口 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/` | GET | 主页 | 无 |
| `/status` | GET | 获取/设置状态 | mode, devicepwd, ... |
| `/scanap` | GET | 扫描WiFi | 无 |
| `/setwifi` | GET | 配置WiFi | ssid, pwd, serverurl, ... |
| `/reset` | GET | 重置配置 | devicepwd |
| `/restart` | GET | 重启设备 | devicepwd |
| `/static/<path>` | GET | 静态资源 | 文件路径 |
| `/favicon.ico` | GET | 网站图标 | 无 |

### 5.2 `/status` API 详细设计

#### 5.2.1 查询模式 (mode=get)

**请求**: `/status?mode=get&devicepwd=xxx`

**响应**:
```json
{
    "errCode": "0",
    "mode": "normal",
    "sw1": true,
    "sw2": false,
    "sw1name": "灯光",
    "sw2name": "风扇",
    "temp": 25.6,
    "humi": 65.2,
    "wetBulbTemp": 20.3,
    "presure": 101325,
    "luminance": -9999,
    "pm25": -9999,
    "runTime": 12345,
    "totalRunTime": 123456,
    "totalSprayCount": 50,
    "totalAddWaterCount": 10,
    "fineTempThreshold": 31.5,
    "fineHThreshold": 36.0,
    "fineLThreshold": 31.5,
    "sprayPeriod": 40,
    "minSparyTime": 5,
    "maxSparyTime": 12,
    "minAddWaterInterval": 2400,
    "waterFillTimeOut": 850,
    "waterDischargeTimeOut": 60,
    "waterTDSThreshold": 15,
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
    "pwm4freq": 25000,
    "pwm4min": 15,
    "pwm4max": 100,
    "pwm4default": 0,
    "waterMark": 3,
    "waterAvailable": true,
    "inWaterTDS": 14.3,
    "inWaterTemp": 22.5,
    "waterTankTDS": 14.05,
    "waterTankTemp": 24.5,
    "airConditionerStatus": 1,
    "deviceId": "E8F60A8A5500",
    "devicename": "Aotomizer",
    "deviceusername": "admin",
    "devicepwd": "pengping",
    "wifiname": "cissco_2g",
    "wifipwd": "xxxxxx",
    "APName": "Atomizer",
    "APPwd": "Changeme_123",
    "serverurl": "http://xxx",
    "ver": "1.1"
}
```

**参数说明**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `runTime` | int | 本次开机运行时间（秒），从 `initialBootTime` 开始计算 |
| `totalRunTime` | int | 累计运行时间（秒），设备总运行时间 |
| `sw1name` | str | 开关1名称（支持中文） |
| `sw2name` | str | 开关2名称（支持中文） |
| `waterMark` | int | 水位状态：1=空、2=正常、3=满 |
| `waterAvailable` | bool | 供水状态：true=可用、false=不可用 |
| `airConditionerStatus` | int | 空调状态：0=关、1=开 |
| `inWaterTDS` | float | 进水TDS值 |
| `inWaterTemp` | float | 进水水温 |
| `waterTankTDS` | float | 水箱TDS值 |
| `waterTankTemp` | float | 水箱水温 |
| `waterTDSThreshold` | int | TDS阈值（ppm） |

#### 5.2.2 设置模式 (mode=set)

**请求**: `/status?mode=set&devicepwd=xxx&fineHThreshold=42&fineLThreshold=37.5&sw1=true&sw2=false&...`

**可设置参数**:
- fineHThreshold: 温度高阈值
- fineLThreshold: 温度低阈值
- pwm1freq/pwm1min/pwm1max/pwm1default: PWM1参数
- pwm2freq/pwm2min/pwm2max/pwm2default: PWM2参数
- pwm3freq/pwm3min/pwm3max/pwm3default: PWM3参数
- pwm4freq/pwm4min/pwm4max/pwm4default: PWM4参数
- sw1/sw2: 开关状态
- sw1name/sw2name: 开关名称（支持中文）
- minAddWaterInterval: 补水间隔
- waterFillTimeOut: 补水超时
- waterDischargeTimeOut: 排水超时
- waterTDSThreshold: TDS阈值
- minSparyTime: 最小喷雾时间
- maxSparyTime: 最大喷雾时间
- sprayPeriod: 喷雾周期

**响应**:
```json
{
    "errCode": "0",
    "msg": "set finish."
}
```

### 5.3 `/setwifi` API 详细设计

**请求**: `/setwifi?ssid=xxx&pwd=xxx&serverurl=xxx&devicepwd=xxx&devicename=xxx&sw1name=xxx&sw2name=xxx`

**流程**:
1. 测试WiFi连接
2. 保存配置到数据库
3. 设置重启定时器 (10秒后重启)

**响应**:
```json
{
    "errCode": "0",
    "msg": "connect wifi success and node will reboot after 5s.",
    "APName": "xxx",
    "url": "192.168.x.x"
}
```

---

## 6. 系统配置设计

### 6.1 默认配置

```python
defaulteSystemConfig = {
    "deviceusername": "admin",
    "devicepwd": "pengping",
    "devicename": "Aotomizer",
    "wifiname": "cissco_2g",
    "wifipwd": "13438045703",
    "APName": "Atomizer",
    "APPwd": "Changeme_123",
    "APIP": "123",
    "APGateway": "192.168.1.1",
    "APNetMask": "255.255.255.0",
    "serverurl": "http://3a892544f7.qicp.vip",
    "mode": "normal",
    "sw1": True,
    "sw2": False,
    "sw1name": "S1",
    "sw2name": "S2",
    "fineHThreshold": 36,
    "fineLThreshold": 31.5,
    "modbusSlaveAddr": 6,
    "modbusBadud": 38400,
    "deviceId": "",
    "waterTDSThreshold": 15,
    "waterDischargeTimeOut": 60,
    "waterFillTimeOut": 850,
    "minAddWaterInterval": 2400,
    "sprayPeriod": 40,
    "minSparyTime": 5,
    "maxSparyTime": 12,
    "pwm1freq": 25000,
    "pwm1default": 0,
    "pwm1min": 15,
    "pwm1max": 100,
    "pwm2freq": 25000,
    "pwm2default": 0,
    "pwm2min": 15,
    "pwm2max": 100,
    "pwm3freq": 25000,
    "pwm3default": 0,
    "pwm3min": 15,
    "pwm3max": 100,
    "pwm4freq": 25000,
    "pwm4default": 0,
    "pwm4min": 15,
    "pwm4max": 100,
    "altitude": 498,
    "latitude": 30.67831,
    "longitude": 104.0375,
    "wifinameDefault": "IOT_2G",
    "wifipwdDefault": "13438045703",
    "ver": "1.1"
}
```

### 6.2 运行模式

| 模式 | 说明 | 行为 |
|------|------|------|
| normal | 正常运行模式 | 连接WiFi，运行状态机，广播IP |
| config | 配置模式 | 启动AP，等待WiFi配置，300秒超时重启 |

### 6.3 参数分组配置

参数按相关性智能分组，便于前端显示和管理：

| 分组 | 参数 |
|------|------|
| 温度阈值 | fineHThreshold, fineLThreshold |
| 喷雾参数 | sprayPeriod, minSparyTime, maxSparyTime, waterTDSThreshold |
| PWM配置 | pwm1freq, pwm1min, pwm1max, pwm1default, pwm2freq, pwm2min, pwm2max, pwm2default, pwm3freq, pwm3min, pwm3max, pwm3default, pwm4freq, pwm4min, pwm4max, pwm4default |
| 补水参数 | minAddWaterInterval, waterFillTimeOut, waterDischargeTimeOut |
| 开关配置 | sw1, sw2, sw1name, sw2name |
| 网络配置 | wifiname, wifipwd, APName, APPwd, serverurl |

**参数类型转换**: DBUtil仅支持字符串存储，读取时需根据实际需要转换为对应类型：
- 数值型参数: `int(db.get("totalRunTime"))`
- 布尔型参数: `bool(db.get("sw1"))`

---

## 7. 系统启动流程

### 7.1 启动流程图

```
boot.py 执行
    ↓
main.py 执行
    ↓
加载/创建系统配置 (DBUtils)
    ↓
生成设备UUID (首次启动)
    ↓
初始化 BSP (单例)
    ↓
初始化状态机 (AotomizerFSM + WaterProcessFSM)
    ↓
启动看门狗定时器 (60秒超时, 5秒喂狗)
    ↓
判断运行模式
    ├── normal模式 → 连接WiFi → 成功 → 广播IP线程 → Web服务器线程 → 主循环
    │                ↓
    │                失败 → config模式
    │
    └── config模式 → 启动AP → 配置定时器(300秒) → Web服务器线程 → 等待配置
```

### 7.2 主循环逻辑

```python
while True:
    sysTask()           # 更新运行时间计数
    runFSM()            # 运行状态机
    gc.collect()        # 每300次循环执行GC
    setLEDArray()       # LED闪烁指示
    saveData()          # 每3600次保存数据
    utime.sleep_ms(1000)
    loopCounter += 1
```

### 7.3 全局变量说明

| 变量 | 类型 | 用途 | 说明 |
|------|------|------|------|
| `bootTime` | int | 累计运行时间计算 | 被 `sysTask()` 不断更新，用于计算 `totalRunTime` |
| `initialBootTime` | int | 本次开机运行时间计算 | 初始启动时间，不会被更新，用于计算 `runTime` |
| `totalRunTime` | int | 累计运行时间 | 设备总运行时间（秒），定期保存到数据库 |
| `loopCounter` | int | 循环计数器 | 用于定时执行任务（GC、LED闪烁、数据保存） |
| `whenGotoConfigMode` | int | 配置模式超时 | 记录进入配置模式的时间，超时300秒后重启 |
| `gotIpLast` / `gotIpNow` | str | IP地址检测 | 检测IP变化，用于广播通知 |
| `LEDArrayColor` | tuple | LED颜色 | 当前LED显示颜色 |

---

## 8. LED 状态指示

| 颜色 | 状态 | 说明 |
|------|------|------|
| 红色 (255,0,0) | 启动中 | 系统初始化 |
| 绿色 (0,255,0) | WiFi已连接 | 正常运行，IP获取成功 |
| 蓝色 (0,0,255) | 配置模式 | AP模式等待配置 |
| 紫色 (255,0,255) | WiFi断开 | Station模式连接失败 |
| 白色 (255,255,255) | BSP初始化完成 | 硬件就绪 |
| 闪烁 | 运行中 | 每2秒闪烁一次 |

---

## 9. 安全设计

### 9.1 认证机制
- 所有敏感API需要 `devicepwd` 参数验证
- 默认密码: `pengping`

### 9.2 目录遍历防护
```python
if '..' in fileName:
    return 'Not found', 404
```

### 9.3 看门狗机制
- 超时时间: 60秒
- 喂狗周期: 5秒
- 防止系统死锁

### 9.4 中文参数支持

**问题**: Microdot框架的 `urldecode_str` 函数无法正确解码UTF-8多字节字符，导致中文参数传递时出现乱码。

**解决方案**:
1. **前端**: 使用 `encodeURIComponent()` 对中文参数进行URL编码
   ```javascript
   encodeURIComponent("灯光") → "%E7%81%AF%E5%85%89"
   ```

2. **后端**: 修改 `lib/microdot.py` 中的 `urldecode_str` 和 `urldecode_bytes` 函数，先将所有 `%XX` 转换为字节值，构建完整的字节数组，然后统一用 `decode('utf-8')` 解码

**支持中文的参数**:
- `sw1name`: 开关1名称
- `sw2name`: 开关2名称
- `devicename`: 设备名称

---

## 10. 前端界面设计

### 10.1 架构设计

**模块化架构**:
```
index.html
├── CONFIG模块      # 常量配置（选择器、API地址、单位等）
├── UTILS模块       # 工具函数（格式化、JSON解析等）
├── VIEW模块        # 视图层（工厂模式创建专用视图）
├── CONTROLLER模块  # 控制器层（刷新控制器、事件控制器）
└── App主模块       # 应用入口
```

**设计模式**:
- **工厂模式**: 视图创建通过工厂函数实现，降低耦合度
- **关注点分离**: 视图层与控制器层分离，便于维护

### 10.2 功能模块（Tabs标签页）

| 标签页 | 功能 |
|--------|------|
| 设备状态 | 设备名称、运行时间、传感器实时数据、温度/湿度图表 |
| 参数设置 | 温度阈值、喷雾参数、PWM参数（4通道）、补水参数分组显示 |
| 开关控制 | S1/S2开关控制及名称设置 |
| 网络配置 | WiFi扫描、连接配置、设备名称/密码设置 |

### 10.3 响应式布局

| 屏幕宽度 | 显示列数 |
|----------|----------|
| < 600px | 1列（手机） |
| 600px - 960px | 2列（平板） |
| 960px - 1280px | 3列（桌面） |
| >= 1280px | 4列（大屏） |

**布局实现**: 使用CSS Grid配合媒体查询，参数分组显示在网格中。

### 10.4 数据刷新机制
- 定时器周期: 5秒
- 自动刷新传感器数据
- 图表数据缓存: 350条记录 (约30分钟)

### 10.5 界面显示优化

**动态颜色显示**:
- **供水状态**: 可用时绿色，不可用时红色
- **翅片温度**: >温度低阈值时红色，反之绿色
- **水位状态**: 空=红色、正常=绿色、满=绿色

**中文显示**:
- 空调状态: ON→开, OFF→关
- 开关状态: ON→开, OFF→关

---

## 11. 线程设计

| 线程 | 功能 | 栈大小 |
|------|------|--------|
| 主线程 | 状态机运行、LED控制、数据保存 | 默认 |
| WebApp线程 | Web服务器运行 | 32KB |
| broadcastIPInfo线程 | IP广播、WiFi状态监测 | 默认 |

---

## 12. 错误处理

### 12.1 传感器故障
- 返回 `-9999` 表示传感器故障
- 自动重试初始化硬件

### 12.2 WiFi连接失败
- 35秒超时后进入配置模式
- 配置模式300秒超时后重启

### 12.3 补水超时
- 850秒超时后停止补水
- 记录补水时间，防止频繁补水

### 12.4 参数类型转换错误
- 所有数值型参数在读取时进行类型转换
- 设置参数时验证值有效性，避免空值导致的转换错误

---

## 13. 性能优化

### 13.1 内存管理
- 每300次循环执行GC
- 使用 `micropython.mem_info()` 监控内存

### 13.2 状态机优化
- 状态映射表替代if-else
- 单例模式减少对象创建

### 13.3 湿球温度计算优化
- 二分法替代线性搜索
- 预计算常量减少重复计算

---

## 14. 扩展预留

### 14.1 预留接口
- PWM3/PWM4: 预留风扇控制
- 喷雾电磁阀3: 预留第三个喷头
- TDS传感器: 水质检测（已实现）
- 光照度传感器: 预留luminance字段
- PM2.5传感器: 预留pm25字段

### 14.2 预留参数
- modbusSlaveAddr: Modbus通信预留
- modbusBadud: Modbus波特率预留

---

## 15. 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 202606240000 | 2026-06-24 | 更新TDS驱动、传感器数据类、WaterProcessFSM、前端优化 |
| 202606170000 | 2026-06-17 | 更新全局变量设计、前端架构、参数分组、中文支持 |
| 202606141506 | 2026-06-14 | 初始版本 |

---

## 16. 参考资料

- [MicroPython 官方文档](https://docs.micropython.org/)
- [ESP32-S3 技术参考手册](https://www.espressif.com/)
- [Microdot Web框架](https://github.com/miguelgrinberg/microdot)
- [HDC1080 数据手册](https://www.ti.com/)
- [BMP280 数据手册](https://www.bosch-sensortec.com/)
- [TDS传感器协议文档](https://www.dfrobot.com/)