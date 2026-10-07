from domain.LogUtils import log
import machine
from machine import Timer
from lib.microdot import Microdot, send_file
import domain.wifi as wifi
import domain.fileUtils as fileUtils
import utime, ujson
import driver.bsp as bsp
import domain.AotomizerFSM as aotomizerFSM
import domain.WaterProcessFSM as waterProcessFSM
import domain.DBUtils as db
import domain.ntpSync as ntpSync
import _thread
import gc
import micropython as mp

# 固件使用：ESP32_GENERIC_S3-SPIRAM_OCT-20250415-v1.25.0.bin
LEDArrayColor = (255, 0, 0)
# from machine import RTC
# rtc = RTC()
# rtc.datetime((2024, 1, 1, 12, 0, 0, 0, 0))
# log(rtc.datetime())


# default systemConfig
log("software version:202606141506")
log("start begin...")

defaulteSystemConfig = {
    "deviceusername": "admin",
    "devicepwd": "pengping",
    "wifiname": "cissco_2g",
    "wifipwd": "13438045703",
    "wifipwdDefault": "13438045703",
    "devicetype": "Micropython",
    "APName": "Atomizer",
    "sw2name": "S2",
    "APNetMask": "255.255.255.0",
    "altitude": 498,
    "wifinameDefault": "IOT_2G",
    "latitude": 30.67831,
    "serverurl": "http://3a892544f7.qicp.vip",
    "APPwd": "Changeme_123",
    "devicename": "Aotomizer",
    "mode": "normal",
    "sw1name": "S1",
    "APGateway": "192.168.1.1",
    "APIP": "123",
    "longitude": 104.0375,
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
    "sw1": True,
    "sw2": False,
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
    "ver": "1.1"
}

systemConfig = db.get("systemConfig")

if systemConfig is not None:
    stored = None
    try:
        stored = ujson.loads(systemConfig)
    except ValueError:
        pass
    if not isinstance(stored, dict):
        log("[ERROR]systemConfig in DB invalid, fallback to defaults.")
        stored = {}
    # F10：与出厂默认配置合并——老数据库缺少的新增字段取默认值，
    # 防止固件升级后访问缺失字段 KeyError 导致启动失败（合并结果在下次保存配置时落库）
    systemConfig = dict(defaulteSystemConfig)
    systemConfig.update(stored)
    log("systemConfig in DB:{}".format(systemConfig))
else:
    log("create default systemConfig:{}...".format(
        ujson.dumps(defaulteSystemConfig)))
    db.save({"systemConfig": ujson.dumps(defaulteSystemConfig)})
    systemConfig = dict(defaulteSystemConfig)

# 初始化设备 UUID
if "deviceId" not in systemConfig or not systemConfig["deviceId"]:
    systemConfig["deviceId"] = machine.unique_id().hex().upper()
    log("Generated device UUID:{}".format(systemConfig["deviceId"]))
    db.save({"systemConfig": ujson.dumps(systemConfig)})
else:
    log("Device UUID:{}".format(systemConfig["deviceId"]))


def createDefaultConfig():
    log("create default config...")
    db.delete("systemConfig")
    db.save({"systemConfig": ujson.dumps(defaulteSystemConfig)})

loopCounter = 0  # 循环序号，仅作 feedDog 日志序号（定时判断已改为真实时间驱动）
# 运行时长用毫秒节拍"累计"计算（不依赖 utime.time()——NTP 对时后系统时间会向前跳变，
# 墙钟差值会导致 runTime/totalRunTime 突变为巨大值）。
# 每轮主循环累加毫秒差、输出时再换算秒：
# ① 累计对象是每轮约 1s 的间隔，永远处于 ticks_diff 安全窗口（差值 < 2^29ms ≈ 6.21 天）内，
#    避免"距开机时长"超窗口后 runTime 变负数（ticks_ms 以 2^30ms 回绕）
# ② 毫秒精确累计不丢余数，避免每轮 //1000 整除导致 totalRunTime 累计偏慢 2~9%
runMs = 0  # 本次开机运行毫秒数（输出 runTime = runMs // 1000）
lastSysTick = utime.ticks_ms()  # sysTask 上次采样时刻（每轮刷新）

totalRunTimeMs = 0  # 跨开机累计运行毫秒数（DB 中仍以秒为单位存储）
if db.get("totalRunTime") is not None:
    totalRunTimeMs = int(db.get("totalRunTime")) * 1000
else:
    db.save({"totalRunTime": "0"})


bspInstance = bsp.BSP()
bspInstance.setConfig(systemConfig)

log("init FSM...")
fsmList = {
    "aotomizerFSM": aotomizerFSM.FSM(bspInstance, systemConfig),
    "waterProcessFSM": waterProcessFSM.FSM(bspInstance, systemConfig)
}


def runFSM():
    for item in fsmList.values():
        item.run()


def closeFSM():
    for item in fsmList.values():
        item.close()


def reloadConfigFSM():
    for item in fsmList.values():
        item.reloadConfig()


# 初始化看门狗定时器，超时时间为60秒
wdt = machine.WDT(timeout=60000)

# 主循环活性检测：主循环每轮调用updateAliveTick()刷新时间戳，
# feedDog仅在主循环存活时喂狗；主循环卡死则停止喂狗，由WDT触发芯片复位。
# （修复R1：原实现由Timer回调无条件喂狗，主循环卡死时看门狗永远不会复位）
lastAliveTick = utime.ticks_ms()
ALIVE_TIMEOUT_MS = 30000  # 主循环超过30秒未刷新视为卡死（正常每轮约1秒）


def updateAliveTick():
    global lastAliveTick
    lastAliveTick = utime.ticks_ms()


def feedDog(timer):
    global lastAliveTick
    now = utime.ticks_ms()
    if utime.ticks_diff(now, lastAliveTick) < ALIVE_TIMEOUT_MS:
        wdt.feed()
        log("{}:feed dog-----------".format(loopCounter))
    else:
        log("[WARN]main loop blocked {}ms, stop feeding WDT.".format(
            utime.ticks_diff(now, lastAliveTick)))


WDTTimer = Timer(0)
WDTTimer.init(mode=Timer.PERIODIC, period=15000, callback=feedDog)


def saveData():
    global totalRunTimeMs
    db.save({"totalRunTime": str(totalRunTimeMs // 1000)})


# 超时或者自动重连上了就会自动退出
def ModeTimerHandler(timer):
    log("config mode left {}s to exit.".format(
        MAX_CONFIG_MODE_TIME_IN_SECONDS - (utime.time() - whenGotoConfigMode)))
    status = wifi.isConnected()
    if status or ((utime.time() - whenGotoConfigMode) > MAX_CONFIG_MODE_TIME_IN_SECONDS):
        log("reboot after 5s.")
        wifi.stopAP()
        utime.sleep_ms(5000)
        machine.reset()


def createConfigTimer(seconds):
    modeTimer = Timer(3)
    modeTimer.init(mode=Timer.PERIODIC, period=seconds * 1000,
                   callback=ModeTimerHandler)


log("start finish.")

# wifi.startAP(systemConfig["APName"],"880612")

MAX_CONFIG_MODE_TIME_IN_SECONDS = 300
whenGotoConfigMode = 0

# 启动直接则尝试连接wifi，连接成功则直接连接，如果连接失败，则启动AP模式
# AP模式最长等待300s，如果300s仍然没有完成配置，则直接重启，如此往复
# 在配置模式，配置成功wifi后，10s后自动重启

gotIpLast = ""
gotIpNow = ""


def broadcastIPInfo(name):
    global gotIpLast
    global gotIpNow
    global LEDArrayColor
    while True:
        log("{}:detect IP info...".format(name))
        gotIpNow = wifi.getStationIP()
        if gotIpNow and gotIpLast != gotIpNow:
            broadcastName = systemConfig["devicename"] + "_" + gotIpNow
            wifi.startAP(broadcastName, systemConfig["APPwd"])
            log("---------------IP changed. now:{}, last:{}".format(
                gotIpNow, gotIpLast))
            gotIpLast = gotIpNow
        elif gotIpNow:
            log("get IP success:{}".format(gotIpNow))
            LEDArrayColor = (0, 255, 0)
            bspInstance.setLEDArray(LEDArrayColor)
        else:
            LEDArrayColor = (255, 0, 255)
            bspInstance.setLEDArray(LEDArrayColor)
            log("get IP failed.")
        utime.sleep_ms(60000)


if "normal" == systemConfig["mode"] and wifi.connectToWifi(
        systemConfig["wifiname"], systemConfig["wifipwd"]):
    log("connect wifi success. broadcast node ip.")
    _thread.start_new_thread(broadcastIPInfo, ("Thread-broadcastIPInfo",))
else:
    systemConfig["mode"] = "config"
    LEDArrayColor = (0, 0, 255)
    bspInstance.setLEDArray(LEDArrayColor)
    log("start config mode...")

    whenGotoConfigMode = utime.time()
    wifi.startAP(systemConfig["APName"], systemConfig["APPwd"], True)
    createConfigTimer(10)

# 初始化webserver
app = Microdot()


# 返回主页
@app.route('/')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    return send_file('/static/index.html')


@app.route('/favicon.ico')
def handler(request):
    if len(request.path) > 1:
        fileName = request.path[1:]
    else:
        return 'file name invalid:{}'.format(request.path), 404

    if '..' in fileName or not fileUtils.isFileExist("/static/", fileName):
        return 'Not found:{}'.format(fileName), 404
    return send_file('/static/' + fileName)


@app.route('/static/<path:path>')
def handler(request, path):
    if '..' in path or not fileUtils.isFileExist("/static/", path):
        return 'Not found', 404
    return send_file('/static/' + path)


@app.get('/status')
def handler(request):
    global whenGotoConfigMode
    global totalRunTimeMs
    global systemConfig
    whenGotoConfigMode = utime.time()
    if "devicepwd" not in request.args or request.args["devicepwd"] != systemConfig["devicepwd"]:
        res = {"errCode": "-1", "msg": "invalid device password."}
        return ujson.dumps(res)
    elif "mode" in request.args and request.args["mode"] == "get":
        res = {
            "errCode": "0",
            "mode": systemConfig.get("mode", "normal"),
            "sw1": systemConfig.get("sw1", True),
            "sw2": systemConfig.get("sw2", False)
        }
        res.update(systemConfig)
        if "sw1" not in res:
            res["sw1"] = True
        if "sw2" not in res:
            res["sw2"] = False

        res["temp"] = bspInstance.getSensorData().temp
        res["humi"] = bspInstance.getSensorData().humi
        res["wetBulbTemp"] = bspInstance.getSensorData().wetBulbTemp
        res["presure"] = bspInstance.getSensorData().presure
        res["luminance"] = bspInstance.getSensorData().luminance
        res["pm25"] = bspInstance.getSensorData().pm25
        res["runTime"] = runMs // 1000  # 本次开机运行时间（秒）
        res["totalRunTime"] = totalRunTimeMs // 1000
        res.update(fsmList["aotomizerFSM"].getStatus())
        res.update(fsmList["waterProcessFSM"].getStatus())

        return ujson.dumps(res)
    elif "mode" in request.args and request.args["mode"] == "set":
        # R4：先整体校验数值参数，全部合法才应用（防止单个异常值破坏运行逻辑）
        errors = validateSetArgs(request.args)
        if errors:
            res = {"errCode": "-1", "msg": "invalid params: " + "; ".join(errors)}
            log("[WARN]set config rejected:{}".format(res["msg"]))
            return ujson.dumps(res)

        res = {"errCode": "0", "msg": "set finish."}

        # 温度阈值参数
        if "fineHThreshold" in request.args:
            systemConfig["fineHThreshold"] = float(request.args["fineHThreshold"])
        if "fineLThreshold" in request.args:
            systemConfig["fineLThreshold"] = float(request.args["fineLThreshold"])

        # 兼容旧接口 PWM 参数
        if "pwmFreq" in request.args:
            systemConfig["pwm1freq"] = int(request.args["pwmFreq"])
        if "pwmMinDuty" in request.args:
            systemConfig["pwm1min"] = int(request.args["pwmMinDuty"])
        if "pwmMaxDuty" in request.args:
            systemConfig["pwm1max"] = int(request.args["pwmMaxDuty"])

        # PWM1 参数
        if "pwm1freq" in request.args:
            systemConfig["pwm1freq"] = int(request.args["pwm1freq"])
        if "pwm1min" in request.args:
            systemConfig["pwm1min"] = int(request.args["pwm1min"])
        if "pwm1max" in request.args:
            systemConfig["pwm1max"] = int(request.args["pwm1max"])
        if "pwm1default" in request.args:
            systemConfig["pwm1default"] = int(request.args["pwm1default"])

        # PWM2 参数
        if "pwm2freq" in request.args:
            systemConfig["pwm2freq"] = int(request.args["pwm2freq"])
        if "pwm2min" in request.args:
            systemConfig["pwm2min"] = int(request.args["pwm2min"])
        if "pwm2max" in request.args:
            systemConfig["pwm2max"] = int(request.args["pwm2max"])
        if "pwm2default" in request.args:
            systemConfig["pwm2default"] = int(request.args["pwm2default"])

        # PWM3 参数
        if "pwm3freq" in request.args:
            systemConfig["pwm3freq"] = int(request.args["pwm3freq"])
        if "pwm3min" in request.args:
            systemConfig["pwm3min"] = int(request.args["pwm3min"])
        if "pwm3max" in request.args:
            systemConfig["pwm3max"] = int(request.args["pwm3max"])
        if "pwm3default" in request.args:
            systemConfig["pwm3default"] = int(request.args["pwm3default"])

        # PWM4 参数
        if "pwm4freq" in request.args:
            systemConfig["pwm4freq"] = int(request.args["pwm4freq"])
        if "pwm4min" in request.args:
            systemConfig["pwm4min"] = int(request.args["pwm4min"])
        if "pwm4max" in request.args:
            systemConfig["pwm4max"] = int(request.args["pwm4max"])
        if "pwm4default" in request.args:
            systemConfig["pwm4default"] = int(request.args["pwm4default"])

        # 开关状态参数
        if "sw1" in request.args:
            sw1_val_str = str(request.args["sw1"]).lower()
            if sw1_val_str in ["true", "1"]:
                systemConfig["sw1"] = True
            else:
                systemConfig["sw1"] = False
            log("Switch status changed: sw1={}".format(systemConfig["sw1"]))

        if "sw2" in request.args:
            sw2_val_str = str(request.args["sw2"]).lower()
            if sw2_val_str in ["true", "1"]:
                systemConfig["sw2"] = True
            else:
                systemConfig["sw2"] = False
            log("Switch status changed: sw2={}".format(systemConfig["sw2"]))

        # 开关名称参数
        if "sw1name" in request.args:
            systemConfig["sw1name"] = request.args["sw1name"]
        if "sw2name" in request.args:
            systemConfig["sw2name"] = request.args["sw2name"]

        # 喷雾和加水参数
        if "minAddWaterInterval" in request.args:
            systemConfig["minAddWaterInterval"] = int(request.args["minAddWaterInterval"])
        if "minSparyTime" in request.args:
            systemConfig["minSparyTime"] = int(request.args["minSparyTime"])
        if "maxSparyTime" in request.args:
            systemConfig["maxSparyTime"] = int(request.args["maxSparyTime"])
        if "sprayPeriod" in request.args:
            systemConfig["sprayPeriod"] = int(request.args["sprayPeriod"])
        if "waterTDSThreshold" in request.args:
            val = request.args["waterTDSThreshold"]
            if val is not None and val != "" and val != "----":
                systemConfig["waterTDSThreshold"] = int(val)

        # 设备参数
        if "deviceusername" in request.args:
            systemConfig["deviceusername"] = request.args["deviceusername"]
        if "devicename" in request.args:
            systemConfig["devicename"] = request.args["devicename"]
        if "devicepwd" in request.args:
            systemConfig["devicepwd"] = request.args["devicepwd"]

        # WiFi 参数
        if "wifiname" in request.args:
            systemConfig["wifiname"] = request.args["wifiname"]
        if "wifipwd" in request.args:
            systemConfig["wifipwd"] = request.args["wifipwd"]

        # AP 热点参数
        if "APName" in request.args:
            systemConfig["APName"] = request.args["APName"]
        if "APPwd" in request.args:
            systemConfig["APPwd"] = request.args["APPwd"]
        if "APIP" in request.args:
            systemConfig["APIP"] = request.args["APIP"]

        # 服务器参数
        if "serverurl" in request.args:
            systemConfig["serverurl"] = request.args["serverurl"]

        # Modbus 参数
        if "modbusBadud" in request.args:
            systemConfig["modbusBadud"] = int(request.args["modbusBadud"])
        if "modbusSlaveAddr" in request.args:
            systemConfig["modbusSlaveAddr"] = int(request.args["modbusSlaveAddr"])

        log("new systemConfig:{}".format(systemConfig))
        db.save({"systemConfig": ujson.dumps(systemConfig)})

        bspInstance.setConfig(systemConfig)
        log("set config finish")
        reloadConfigFSM()
        return ujson.dumps(res)
    else:
        res = {"errCode": "-1", "msg": "unsupported operation."}
        return ujson.dumps(res)


@app.get('/scanap')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = wifi.scanAP()
    if len(res) > 0:
        log("scanap:{}".format(res))
        return ujson.dumps(res)
    else:
        return "{}"


def maskArgs(args):
    # F7：日志脱敏——过滤密码类参数，避免密码明文进入系统日志
    return {k: v for k, v in args.items()
            if k not in ("pwd", "devicepwd", "APPwd")}


def validateSetArgs(args):
    # R4：/status?mode=set 数值参数范围校验（只读不改）。返回错误消息列表，空列表=全部合法。
    # 跨字段校验（如 min<max）用"新值优先、缺省取当前配置值"的有效值组合，兼容部分更新；
    # 全部通过后才由赋值逻辑统一应用，避免"改了一半校验失败"造成配置不一致。
    errors = []

    def checkNum(key, conv, lo, hi, skipPlaceholder=False):
        if key not in args:
            return
        raw = args[key]
        # waterTDSThreshold 的 "----" 是前端"未修改"占位符（与赋值逻辑的跳过语义一致）
        if skipPlaceholder and raw in ("", "----"):
            return
        try:
            v = conv(raw)
            if v != v:  # NaN 防御
                errors.append("{} must be a number".format(key))
            elif v < lo or v > hi:
                errors.append("{} out of range[{},{}]".format(key, lo, hi))
        except (ValueError, TypeError):
            errors.append("{} must be a number".format(key))

    def effVal(key, conv):
        if key in args:
            return conv(args[key])
        return conv(systemConfig[key])

    def checkPair(a, b, conv):
        # 校验有效值组合下 a < b；当前配置值类型异常时跳过（单边范围已由 checkNum 保证）
        try:
            if effVal(a, conv) >= effVal(b, conv):
                errors.append("{} must be less than {}".format(a, b))
        except (ValueError, TypeError, KeyError):
            pass

    # 温度阈值（℃）与喷雾时长（s）
    checkNum("fineLThreshold", float, -20, 120)
    checkNum("fineHThreshold", float, -20, 120)
    checkPair("fineLThreshold", "fineHThreshold", float)
    checkNum("minSparyTime", int, 1, 3600)
    checkNum("maxSparyTime", int, 1, 3600)
    checkPair("minSparyTime", "maxSparyTime", int)
    checkNum("sprayPeriod", int, 1, 86400)

    # PWM1~4：频率（Hz）与占空比百分数，含 min<max 一致性
    for i in ("1", "2", "3", "4"):
        checkNum("pwm" + i + "freq", int, 1, 78125)
        checkNum("pwm" + i + "min", int, 0, 100)
        checkNum("pwm" + i + "max", int, 0, 100)
        checkNum("pwm" + i + "default", int, 0, 100)
        checkPair("pwm" + i + "min", "pwm" + i + "max", int)
    # 兼容旧接口 PWM 参数
    checkNum("pwmFreq", int, 1, 78125)
    checkNum("pwmMinDuty", int, 0, 100)
    checkNum("pwmMaxDuty", int, 0, 100)

    # 加水（s）与 TDS 阈值、Modbus
    checkNum("minAddWaterInterval", int, 0, 2592000)
    checkNum("waterFillTimeOut", int, 1, 86400)
    checkNum("waterDischargeTimeOut", int, 1, 86400)
    checkNum("waterTDSThreshold", int, 0, 10000, skipPlaceholder=True)
    checkNum("modbusBadud", int, 1, 115200)
    checkNum("modbusSlaveAddr", int, 1, 247)

    return errors


# setwifi?ssid=3&pwd=123456&serverurl=192.168.1.124&devicepwd=pengping
# &devicename=----&sw1name=----&sw2name=----
@app.get('/setwifi')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success", "APName": "APName", "url": "url"}
    log("setwifi:path:{} ".format(request.path))
    log("setwifi:args:{}".format(maskArgs(request.args)))
    # F7：必填参数校验，缺失时返回错误码而不是抛 KeyError 导致 500
    required = ("ssid", "pwd", "devicename", "devicepwd", "serverurl", "sw1name", "sw2name")
    missing = [k for k in required if k not in request.args or request.args[k] == ""]
    if len(missing) > 0:
        res["errCode"] = "-1"
        res["msg"] = "missing required params:{}".format(",".join(missing))
        return ujson.dumps(res)
    ssid = request.args["ssid"]
    pwd = request.args["pwd"]
    if wifi.testWifiConnect(ssid, pwd):
        systemConfig["sw1name"] = request.args["sw1name"]
        systemConfig["sw2name"] = request.args["sw2name"]
        systemConfig["devicename"] = request.args["devicename"]
        systemConfig["devicepwd"] = request.args["devicepwd"]
        systemConfig["serverurl"] = request.args["serverurl"]
        systemConfig["wifiname"] = ssid
        systemConfig["wifipwd"] = pwd
        systemConfig["mode"] = "normal"

        # 可选参数
        if "deviceusername" in request.args:
            systemConfig["deviceusername"] = request.args["deviceusername"]
        if "APName" in request.args:
            systemConfig["APName"] = request.args["APName"]
        if "APPwd" in request.args:
            systemConfig["APPwd"] = request.args["APPwd"]
        if "APIP" in request.args:
            systemConfig["APIP"] = request.args["APIP"]
        if "modbusBadud" in request.args:
            systemConfig["modbusBadud"] = int(request.args["modbusBadud"])
        if "modbusSlaveAddr" in request.args:
            systemConfig["modbusSlaveAddr"] = int(request.args["modbusSlaveAddr"])

        db.save({"systemConfig": ujson.dumps(systemConfig)})
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 10
        log("reboot after 10s.")
        createConfigTimer(10)
        res["APName"] = ssid
        # getStationIP 失败返回 None（P1-4），兜底空串避免 JSON null
        res["url"] = wifi.getStationIP() or ""
        res["errCode"] = "0"
        res["msg"] = "connect wifi success and node will reboot after 5s."
    else:
        systemConfig["mode"] = "config"
        res["errCode"] = "-1"
        res["msg"] = "connect wifi or save config failed."

    return ujson.dumps(res)


@app.get('/reset')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success"}
    log("reset:path:{} ".format(request.path))
    log("reset:args:{}".format(maskArgs(request.args)))

    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        log("reset after 5s.")
        createDefaultConfig()
        createConfigTimer(5)
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 5
    else:
        res["errCode"] = "-1"
        res["msg"] = "invalid device passwd."

    return ujson.dumps(res)


# 重启命令 http://192.168.30.254/restart?devicepwd=pengping
@app.get('/restart')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success"}
    log("restart:path:{} ".format(request.path))
    log("restart:args:{}".format(maskArgs(request.args)))

    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        log("reboot after 5s.")
        closeFSM()
        createConfigTimer(5)
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 5
    else:
        res["errCode"] = "-1"
        res["msg"] = "invalid device passwd."

    return ujson.dumps(res)


def runWebApp(name):
    log("start web app:{}...".format(name))
    app.run(host='0.0.0.0', port=80, debug=False, ssl=None)


try:
    _thread.stack_size(32 * 1024)
    _thread.start_new_thread(runWebApp, ("Thread:WebApp",))
except OSError as e:
    log(f"Error starting thread: {e}")


# NTP 对时调度（两阶段，由"首次校时成功"标记切换）：
#   阶段1：首次校时未成功（ntpSynced=False）→ 每 60s 重试，直到首次校时成功
#   阶段2：首次校时已成功（ntpSynced=True）→ 每 1 周重新校时一次
# 跳变安全设计：
#   - 60s 重试节流用 ticks_ms 单调节拍，完全不受 RTC 跳变影响
#   - 1 周周期用 utime.time() 判断，但 ntpLastSync 只在首次校时成功后才取样
#     （此时系统时间已从 1970 跳变到真实时间且不再跳变），跳变无法污染周期判断
NTP_RETRY_INTERVAL_S = 60  # 首次校时成功前的重试周期
NTP_RESYNC_INTERVAL_S = 7 * 24 * 3600  # 首次校时成功后的周期校时间隔：1 周
ntpSynced = False  # 首次校时成功标记：只有校时真正成功才置 True
ntpLastTryTick = -NTP_RETRY_INTERVAL_S * 1000  # 负初始值：开机后首轮循环立即尝试第一次
ntpLastSync = 0  # 最近一次成功校时的墙钟时刻（首次成功后才取样，用于 1 周周期判断）


def tryNtpSync():
    global ntpSynced, ntpLastTryTick, ntpLastSync
    if not wifi.isConnected():
        return
    # 60s 重试节流（单调节拍，不受 RTC 跳变影响）
    nowTick = utime.ticks_ms()
    if utime.ticks_diff(nowTick, ntpLastTryTick) < NTP_RETRY_INTERVAL_S * 1000:
        return
    # 周期校时门槛：只有首次校时成功后才启用 1 周周期判断
    if ntpSynced and (utime.time() - ntpLastSync) < NTP_RESYNC_INTERVAL_S:
        return
    ntpLastTryTick = nowTick
    if ntpSync.syncRtc():
        ntpSynced = True  # 刷新首次校时成功标记
        # 此刻系统时间已完成跳变（1970 → 真实时间），取样才有正确基准
        ntpLastSync = utime.time()


def sysTask():
    global runMs, totalRunTimeMs, lastSysTick
    nowTick = utime.ticks_ms()
    # 毫秒精确累计：每轮间隔约 1s（安全窗口内），先累加、输出时才整除转秒，不丢余数
    deltaMs = utime.ticks_diff(nowTick, lastSysTick)
    runMs += deltaMs
    totalRunTimeMs += deltaMs
    lastSysTick = nowTick


# 主循环定时任务时间戳：全部依赖真实时间（RTC 时基 ticks_ms 单调读数），
# 与轮询频率解耦（FSM 10Hz 节拍后各定时行为不变）
loopTick = utime.ticks_ms()
lastGcTick = loopTick
lastLedTick = loopTick
lastMainSaveTick = loopTick
lastWifiCheckTick = loopTick
ledOn = True

# WiFi 断线应用层重连（P1-7）：normal 模式下每 30s 检查一次连接状态，
# 断线则调用 wifi.startReconnect() 做一次射频电源循环（active off→on→connect）
# 完整重建关联与 DHCP，可从长跑假死状态恢复；1s 复位延时不阻塞喂狗（30s 活性窗口），
# 30s 周期即天然退避；断线期间 LED 指示由 broadcastIPInfo 线程按实际连接状态刷新
WIFI_RECONNECT_INTERVAL_MS = 30000


while True:
    updateAliveTick()

    sysTask()

    # NTP 对时（联网后未同步每 60s 重试，成功后每 1 周重新校时）
    tryNtpSync()

    # WiFi 断线重连：normal 模式每 30s 检查，断线则非阻塞发起重连（P1-7）
    if "normal" == systemConfig["mode"] and utime.ticks_diff(loopTick, lastWifiCheckTick) >= WIFI_RECONNECT_INTERVAL_MS:
        lastWifiCheckTick = loopTick
        if not wifi.isConnected():
            log("[WARN]wifi disconnected, try reconnect.")
            wifi.startReconnect(systemConfig["wifiname"], systemConfig["wifipwd"])

    # 运行状态机（10Hz 节拍：100ms）
    runFSM()

    loopTick = utime.ticks_ms()

    # GC + 内存报告：每 5 分钟一次（时间驱动，原为 loopCounter % 300 轮数驱动）
    if utime.ticks_diff(loopTick, lastGcTick) >= 300000:
        lastGcTick = loopTick
        log("-------------Before GC-------------")
        mp.mem_info()
        gc.collect()
        log("-------------After  GC-------------")
        mp.mem_info()

    # 状态 LED 翻转：保持原 2s 节奏（时间驱动，原为 loopCounter % 2 轮数驱动）
    if utime.ticks_diff(loopTick, lastLedTick) >= 2000:
        lastLedTick = loopTick
        ledOn = not ledOn
        bspInstance.setLEDArray(LEDArrayColor if ledOn else (0, 0, 0))

    # 定时落盘：每 1 小时一次（时间驱动，原为 loopCounter % 3600 轮数驱动）
    if utime.ticks_diff(loopTick, lastMainSaveTick) >= 3600000:
        lastMainSaveTick = loopTick
        saveData()
        log("Main:save data to db finish.")

    utime.sleep_ms(100)
    loopCounter += 1