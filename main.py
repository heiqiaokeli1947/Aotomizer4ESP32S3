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
import _thread
import gc
import micropython as mp

# 固件使用：ESP32_GENERIC_S3-SPIRAM_OCT-20250415-v1.25.0.bin
LEDArrayColor = (255, 0, 0)
# from machine import RTC
# rtc = RTC()
# rtc.datetime((2024, 1, 1, 12, 0, 0, 0, 0))
# print(rtc.datetime())


# default systemConfig
print("software version:202606141506")
print("start begin...")

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
    "waterTDSThreshold": 10,
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
    systemConfig = ujson.loads(systemConfig)
    print("systemConfig in DB:{}".format(systemConfig))
else:
    print("create default systemConfig:{}...".format(
        ujson.dumps(defaulteSystemConfig)))
    db.save({"systemConfig": ujson.dumps(defaulteSystemConfig)})
    systemConfig = ujson.loads(db.get("systemConfig"))

# 初始化设备 UUID
if "deviceId" not in systemConfig or not systemConfig["deviceId"]:
    systemConfig["deviceId"] = machine.unique_id().hex().upper()
    print("Generated device UUID:{}".format(systemConfig["deviceId"]))
    db.save({"systemConfig": ujson.dumps(systemConfig)})
else:
    print("Device UUID:{}".format(systemConfig["deviceId"]))


def createDefaultConfig():
    print("create default config...")
    db.delete(["systemConfig"])
    db.save({"systemConfig": ujson.dumps(defaulteSystemConfig)})


bootTime = utime.time()  # 记录启动时间，用于计算本次开机运行时间
initialBootTime = bootTime  # 记录初始启动时间（不会被更新）
totalRunTime = 0

if db.get("totalRunTime") is not None:
    totalRunTime = int(db.get("totalRunTime"))
else:
    db.save({"totalRunTime": str(totalRunTime)})


bspInstance = bsp.BSP()
bspInstance.setConfig(systemConfig)

print("init FSM...")
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


def feedDog(timer):
    global loopCounter
    wdt.feed()
    print("{}:feed dog-----------".format(loopCounter))


WDTTimer = Timer(0)
WDTTimer.init(mode=Timer.PERIODIC, period=15000, callback=feedDog)


def saveData():
    global totalRunTime
    db.save({"totalRunTime": str(totalRunTime)})


# 超时或者自动重连上了就会自动退出
def ModeTimerHandler(timer):
    print("config mode left {}s to exit.".format(
        MAX_CONFIG_MODE_TIME_IN_SECONDS - (utime.time() - whenGotoConfigMode)))
    status = wifi.isConnected()
    if status or ((utime.time() - whenGotoConfigMode) > MAX_CONFIG_MODE_TIME_IN_SECONDS):
        print("reboot after 5s.")
        wifi.stopAP()
        utime.sleep_ms(5000)
        machine.reset()


def createConfigTimer(seconds):
    modeTimer = Timer(3)
    modeTimer.init(mode=Timer.PERIODIC, period=seconds * 1000,
                   callback=ModeTimerHandler)


print("start finish.")

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
        print("{}:detect IP info...".format(name))
        gotIpNow = wifi.getStationIP()
        if gotIpNow and gotIpLast != gotIpNow:
            broadcastName = systemConfig["devicename"] + "_" + gotIpNow
            wifi.startAP(broadcastName, systemConfig["APPwd"])
            print("---------------IP changed. now:{}, last:{}".format(
                gotIpNow, gotIpLast))
            gotIpLast = gotIpNow
        elif gotIpNow:
            print("get IP success:{}".format(gotIpNow))
            LEDArrayColor = (0, 255, 0)
            bspInstance.setLEDArray(LEDArrayColor)
        else:
            LEDArrayColor = (255, 0, 255)
            bspInstance.setLEDArray(LEDArrayColor)
            print("get IP failed.")
        utime.sleep_ms(60000)


if "normal" == systemConfig["mode"] and wifi.connectToWifi(
        systemConfig["wifiname"], systemConfig["wifipwd"]):
    print("connect wifi success. broadcast node ip.")
    _thread.start_new_thread(broadcastIPInfo, ("Thread-broadcastIPInfo",))
else:
    systemConfig["mode"] = "config"
    LEDArrayColor = (0, 0, 255)
    bspInstance.setLEDArray(LEDArrayColor)
    print("start config mode...")

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
    global totalRunTime
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
        res["runTime"] = utime.time() - initialBootTime  # 本次开机运行时间（秒）
        res["totalRunTime"] = totalRunTime
        res.update(fsmList["aotomizerFSM"].getStatus())
        res.update(fsmList["waterProcessFSM"].getStatus())

        return ujson.dumps(res)
    elif "mode" in request.args and request.args["mode"] == "set":
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
            print("Switch status changed: sw1={}".format(systemConfig["sw1"]))

        if "sw2" in request.args:
            sw2_val_str = str(request.args["sw2"]).lower()
            if sw2_val_str in ["true", "1"]:
                systemConfig["sw2"] = True
            else:
                systemConfig["sw2"] = False
            print("Switch status changed: sw2={}".format(systemConfig["sw2"]))

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

        print("new systemConfig:{}".format(systemConfig))
        db.save({"systemConfig": ujson.dumps(systemConfig)})

        bspInstance.setConfig(systemConfig)
        print("set config finish")
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
        print("scanap:{}".format(res))
        return ujson.dumps(res)
    else:
        return "{}"


# setwifi?ssid=3&pwd=123456&serverurl=192.168.1.124&devicepwd=pengping
# &devicename=----&sw1name=----&sw2name=----
@app.get('/setwifi')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success", "APName": "APName", "url": "url"}
    print("setwifi:path:{} ".format(request.path))
    print("setwifi:args:{}".format(request.args))
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
        print("reboot after 10s.")
        createConfigTimer(10)
        res["APName"] = ssid
        res["url"] = wifi.getStationIP()
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
    print("reset:path:{} ".format(request.path))
    print("reset:args:{}".format(request.args))

    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        print("reset after 5s.")
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
    print("restart:path:{} ".format(request.path))
    print("restart:args:{}".format(request.args))

    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        print("reboot after 5s.")
        closeFSM()
        createConfigTimer(5)
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 5
    else:
        res["errCode"] = "-1"
        res["msg"] = "invalid device passwd."

    return ujson.dumps(res)


def runWebApp(name):
    print("start web app:{}...".format(name))
    app.run(host='0.0.0.0', port=80, debug=False, ssl=None)


try:
    _thread.stack_size(32 * 1024)
    _thread.start_new_thread(runWebApp, ("Thread:WebApp",))
except OSError as e:
    print(f"Error starting thread: {e}")


def sysTask():
    global totalRunTime
    global bootTime
    currentTime = utime.time()
    totalRunTime += (currentTime - bootTime)
    bootTime = currentTime


loopCounter = 0  # 循环计数器，用于定时判断
while True:
    sysTask()

    # 运行状态机
    runFSM()

    if loopCounter % 300 == 0:
        print("-------------Before GC-------------")
        mp.mem_info()
        gc.collect()
        print("-------------After  GC-------------")
        mp.mem_info()

    if loopCounter % 2 == 0:
        bspInstance.setLEDArray((0, 0, 0))
    else:
        bspInstance.setLEDArray(LEDArrayColor)

    if (loopCounter % 3600) == 0:
        saveData()
        print("Main:save data to db finish.")

    utime.sleep_ms(1000)
    loopCounter += 1