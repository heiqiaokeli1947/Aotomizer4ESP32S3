from domain.LogUtils import log
import utime
import driver.enum as enum
import domain.DBUtils as db

class STATUS:
    INIT = 0
    READY = 1
    AIR_CONDITIONER_ON = 2
    OVER_TEMP = 3
    SPRAY_WATER_1 = 4
    SPRAY_WATER_2 = 5
    SPRAY_WATER_3 = 6
    SPRAY_DELAY = 7


class FSM:
    def __init__(self,bspInstance,config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT
        # runTimeCounterMs 为开机以来的单调毫秒数：run() 内逐轮累加 ticks_diff
        # （每轮间隔约 100ms，恒在 ticks_diff 安全窗口 < 2^29ms 内），与墙钟解耦
        # （NTP 跳变不影响）、与轮询频率解耦（10Hz 节拍）。
        # 不可用 ticks_diff(now, bootTickMs) 对"距开机时长"直接差值——超过 6.21 天后
        # 差值越过安全窗口变负，会导致状态日志/每小时落盘停摆、喷雾超时永不触发
        # （执行器卡死），与 main.py runMs 逐轮累计同模式
        self.lastRunTick = utime.ticks_ms()
        self.runTimeCounterMs = 0
        self.lastLogMs = 0   # 状态日志节流起点（每 1s 打印一次）
        self.lastSaveMs = 0  # "每小时落盘一次"时间边沿判定起点

        self.totalSprayCount = 0
        if db.get("totalSprayCount") is not None:
            self.totalSprayCount = int(db.get("totalSprayCount"))
        else:
            db.save({"totalSprayCount":str(self.totalSprayCount)})

        self.pwmFreq = int(self.config["pwm1freq"])
        self.pwmMinDuty = int(self.config["pwm1min"])
        self.pwmMaxDuty = int(self.config["pwm1max"])

        self.lastSprayTime = 0
        # sprayPeriod 配置单位为秒，内部统一毫秒计时（10Hz 节拍）
        self.sprayPeriod = int(self.config["sprayPeriod"]) * 1000
        self.minSparyTime = int(self.config["minSparyTime"])
        self.maxSparyTime = int(self.config.get("maxSparyTime", 12))
        
        # 初始超时值统一毫秒（10Hz 节拍）
        self.spray1StartTime = 0
        self.spray1TimeOut = 5000

        self.spray2StartTime = 0
        self.spray2TimeOut = 5000

        self.spray3StartTime = 0
        self.spray3TimeOut = 5000


        # 传感器失败值统一 -9999（硬约束）：首个 run() tick 前 Web 查询 /status
        # 不再显示看似有效的 0 读数（BE-1 修复）
        self.finTemp = -9999
        self.humity = -9999
        self.wetBulbTemp = -9999
        self.waterMark = enum.WaterMark.FULL  # 水箱水位（每次 run() 刷新，P1-8）
        self.fineLThreshold = float(self.config["fineLThreshold"])
        self.fineHThreshold = float(self.config["fineHThreshold"])

        self.airConditionerStatus = enum.Switch.OFF

        self.switch = {STATUS.INIT: self.initDevice,
                       STATUS.READY: self.checkAirConditionerStatus,
                       STATUS.AIR_CONDITIONER_ON: self.checkOverTemperature,
                       STATUS.OVER_TEMP: self.overTemp,
                       STATUS.SPRAY_WATER_1: self.checkSpray1Timeout,
                       STATUS.SPRAY_WATER_2: self.checkSpray2Timeout,
                       STATUS.SPRAY_WATER_3: self.checkSpray3Timeout,
                       STATUS.SPRAY_DELAY: self.checkSprayDelayTimeout}
    def setConfig(self,config):
        self.config = config
    
    def getStatus(self):
        return {"totalSprayCount":self.totalSprayCount,
               "fineTempThreshold":self.fineLThreshold,
               "fineTemp":self.finTemp,
               "airConditionerStatus":self.airConditionerStatus}

    def saveData(self):
        db.save({"totalSprayCount":str(self.totalSprayCount)})

    def reloadConfig(self):
        log("reload config:{}".format(self.config))
        self.pwmFreq = int(self.config["pwm1freq"])
        self.pwmMinDuty = int(self.config["pwm1min"])
        self.pwmMaxDuty = int(self.config["pwm1max"])
        # 单位与 __init__ 保持一致：config 秒 → 内部毫秒（P0-1 修复：reload 原漏 ×1000，
        # Web 保存任意配置后 sprayPeriod 变 40ms，导致高温时近乎连续喷雾）
        self.sprayPeriod = int(self.config["sprayPeriod"]) * 1000
        self.minSparyTime = int(self.config["minSparyTime"])
        if "maxSparyTime" in self.config:
            self.maxSparyTime = int(self.config["maxSparyTime"])
        self.fineLThreshold = float(self.config["fineLThreshold"])
        self.fineHThreshold = float(self.config["fineHThreshold"])

    def close(self):
        log("Atomizer FSM:close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkAirConditionerStatus(self):
        if self.airConditionerStatus == enum.Switch.ON:
            self.status = STATUS.AIR_CONDITIONER_ON
        else:
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.status = STATUS.READY

    def checkOverTemperature(self):
        if self.bspInstance.getWaterAvailableStatus() == False:
            log("[ERROR]Water unavailable.")
            self.status = STATUS.READY
        elif self.waterMark == enum.WaterMark.EMPTY:
            # P1-8：水箱空时禁止喷雾——只查水质不查水位会导致空水箱水泵干转烧泵；
            # 等待 WaterProcessFSM 补水，期间设备保持 READY（水泵不启动）
            log("[ERROR]Water tank empty, spray blocked.")
            self.status = STATUS.READY
        elif self.finTemp > self.fineLThreshold:
            self.status = STATUS.OVER_TEMP
            self.totalSprayCount += 1
            self.saveData()
            # 线性+偏置计算喷雾基准时长：翅片温度=低温阈值(fineLThreshold)时为最短时长(minSparyTime)，
            # 达到高温阈值(fineHThreshold)时为最长时长(maxSparyTime)，中间线性过渡，区间外钳位；
            # 配置异常（高温阈值<=低温阈值）时按最短时长兜底
            tempSpan = self.fineHThreshold - self.fineLThreshold
            ratio = 0.0
            if tempSpan > 0:
                ratio = (self.finTemp - self.fineLThreshold) / tempSpan
                if ratio < 0:
                    ratio = 0.0
                elif ratio > 1:
                    ratio = 1.0
            sprayTime = int(self.minSparyTime + (self.maxSparyTime - self.minSparyTime) * ratio)
            # 各路以基准时长为基准，按阀门安装位置（上→下=1/2/3）配比递减：
            # 阀门1=100%，阀门2=70%，阀门3=40%，不足1秒按1秒兜底
            self.spray1TimeOut = sprayTime * 1000
            self.spray2TimeOut = max(1000, int(sprayTime * 0.7) * 1000)
            self.spray3TimeOut = max(1000, int(sprayTime * 0.4) * 1000)
            log("over temp, finTemp:{}, base {}s, spray {}/{}/{}ms.".format(
                self.finTemp, sprayTime, self.spray1TimeOut, self.spray2TimeOut, self.spray3TimeOut))
        else:
            self.status = STATUS.READY

    def openPump(self):
        self.bspInstance.setWaterPump(100)

    def closePump(self):
        self.bspInstance.setWaterPump(0)

    def openSparyEV1(self):
        log("spray 1...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.ON)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.spray1StartTime = self.runTimeCounterMs

    def openSparyEV2(self):
        log("spray 2...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.ON)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.spray2StartTime = self.runTimeCounterMs

    def openSparyEV3(self):
        log("spray 3...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.ON)
        self.spray3StartTime = self.runTimeCounterMs

    def closeAllSparyEV(self):
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)

    def overTemp(self):
        self.openPump()
        self.openSparyEV1()
        self.status = STATUS.SPRAY_WATER_1
    def checkSpray1Timeout(self):
        if self.runTimeCounterMs - self.spray1StartTime >= self.spray1TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            log("spray 1 finish.")
            self.status = STATUS.SPRAY_WATER_2
            self.openPump()
            self.openSparyEV2()
        else:
            return

    def checkSpray2Timeout(self):
        if self.runTimeCounterMs - self.spray2StartTime >= self.spray2TimeOut:
            log("spray 2 finish.")
            self.status = STATUS.SPRAY_WATER_3
            self.openPump()
            self.openSparyEV3()
        else:
            return

    def checkSpray3Timeout(self):
        if self.runTimeCounterMs - self.spray3StartTime >= self.spray3TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            log("spray 3 finish.")
            self.closeAllSparyEV()
            self.closePump()
            self.lastSprayTime = self.runTimeCounterMs
            self.status = STATUS.SPRAY_DELAY
        else:
            return

    def checkSprayDelayTimeout(self):
        if self.runTimeCounterMs - self.lastSprayTime >= self.sprayPeriod:
            log("spray delay finish.")
            # 关闭喷水设备，或者在READY里处理此设备-->转移到self.setDeviceToReadyStatus()
            # self.closeAllSparyEV()
            self.status = STATUS.READY
        else:
            #关闭所有执行器,实际可以依赖上一个状态关闭设备
            self.setDeviceToReadyStatus()
            return

    def getTemperature(self):
        self.finTemp = self.bspInstance.getSensorData().temp
        self.humity = self.bspInstance.getSensorData().humi
        self.wetBulbTemp = self.bspInstance.getSensorData().wetBulbTemp

    def getAirConditonerStatus(self):
        self.airConditionerStatus = self.bspInstance.getAirconditionerStatus()

    def readSystemSensor(self):
        self.getTemperature()
        self.getAirConditonerStatus()
        self.waterMark = self.bspInstance.getWaterTankStatus()  # P1-8：喷雾前水位检查数据源

    def setDeviceToReadyStatus(self):
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.bspInstance.setWaterPump(0)

    def initDevice(self):
        # 初始化设备
        log("[WARN]Atomizer FSM:close all executor.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.READY
        return
    
    def run(self):
        # 逐轮累计单调毫秒（P0-2）：不与开机快照做差，规避 ticks_diff 6.21 天安全窗口
        nowTick = utime.ticks_ms()
        self.runTimeCounterMs += utime.ticks_diff(nowTick, self.lastRunTick)
        self.lastRunTick = nowTick
        self.readSystemSensor()
        # 状态日志节流为每 1s 一次（10Hz 轮询，避免日志刷屏）
        if self.runTimeCounterMs - self.lastLogMs >= 1000:
            self.lastLogMs = self.runTimeCounterMs
            log( "[{}]Atomizer FSM status:{},fineTemp:{},tempThd:{},humi:{},TS:{},Spray count:{},AC status:{}".format(self.runTimeCounterMs // 1000, self.status, self.finTemp, self.fineLThreshold, self.humity, self.wetBulbTemp, self.totalSprayCount, self.airConditionerStatus))

        # 每小时落盘一次（时间边沿触发，与轮询频率解耦；原 %3600 写法在高频轮询下会重复落盘）
        if self.runTimeCounterMs - self.lastSaveMs >= 3600 * 1000:
            self.lastSaveMs = self.runTimeCounterMs
            self.saveData()
            log("AM FSM:save data to db finish.")


        func = self.switch.get(self.status, lambda: log("Atomizer FSM:status not define."))
        return func()

# if __name__=="__main__":
#     fsm = FSM()
#
#     for i in range(50):
#         log("[tick]:{}".format(fsm.timeCounter))
#         fsm.timeCounter = i
#         fsm.run()
