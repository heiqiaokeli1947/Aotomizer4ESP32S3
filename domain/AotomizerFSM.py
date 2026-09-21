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
        # runTimeCounter 为开机以来的单调秒数（ticks_ms 节拍差），与墙钟解耦，
        # NTP 对时跳变不再影响喷雾延时判定与统计落盘（2026-09-21 修复）
        self.bootTickMs = utime.ticks_ms()
        self.runTimeCounter = 0

        self.totalSprayCount = 0
        if db.get("totalSprayCount") is not None:
            self.totalSprayCount = int(db.get("totalSprayCount"))
        else:
            db.save({"totalSprayCount":str(self.totalSprayCount)})

        self.pwmFreq = int(self.config["pwm1freq"])
        self.pwmMinDuty = int(self.config["pwm1min"])
        self.pwmMaxDuty = int(self.config["pwm1max"])

        self.lastSprayTime = 0
        self.sprayPeriod = int(self.config["sprayPeriod"])
        self.minSparyTime = int(self.config["minSparyTime"])
        self.maxSparyTime = int(self.config.get("maxSparyTime", 12))
        
        self.spray1StartTime = 0
        self.spray1TimeOut = 5

        self.spray2StartTime = 0
        self.spray2TimeOut = 5

        self.spray3StartTime = 0
        self.spray3TimeOut = 5


        self.finTemp = 0
        self.humity = 0
        self.wetBulbTemp = 0
        self.fineLThreshold = float(self.config["fineLThreshold"])
        self.fineHThreshold = float(self.config["fineHThreshold"])
    
        self.lastOverTempTime = 0

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
        self.sprayPeriod = int(self.config["sprayPeriod"])
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
        elif self.finTemp > self.fineLThreshold:
            self.status = STATUS.OVER_TEMP
            self.lastOverTempTime = self.runTimeCounter
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
            self.spray1TimeOut = sprayTime
            self.spray2TimeOut = max(1, int(sprayTime * 0.7))
            self.spray3TimeOut = max(1, int(sprayTime * 0.4))
            log("over temp, finTemp:{}, base {}s, spray {}/{}/{}s.".format(
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
        self.spray1StartTime = self.runTimeCounter

    def openSparyEV2(self):
        log("spray 2...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.ON)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.spray2StartTime = self.runTimeCounter

    def openSparyEV3(self):
        log("spray 3...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.ON)
        self.spray3StartTime = self.runTimeCounter

    def closeAllSparyEV(self):
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)

    def overTemp(self):
        self.openPump()
        self.openSparyEV1()
        self.status = STATUS.SPRAY_WATER_1
    def checkSpray1Timeout(self):
        if self.runTimeCounter - self.spray1StartTime >= self.spray1TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            log("spray 1 finish.")
            self.status = STATUS.SPRAY_WATER_2
            self.openPump()
            self.openSparyEV2()
        else:
            return

    def checkSpray2Timeout(self):
        if self.runTimeCounter - self.spray2StartTime >= self.spray2TimeOut:
            log("spray 2 finish.")
            self.status = STATUS.SPRAY_WATER_3
            self.openPump()
            self.openSparyEV3()
        else:
            return

    def checkSpray3Timeout(self):
        if self.runTimeCounter - self.spray3StartTime >= self.spray3TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            log("spray 3 finish.")
            self.closeAllSparyEV()
            self.closePump()
            self.lastSprayTime = self.runTimeCounter
            self.status = STATUS.SPRAY_DELAY
        else:
            return

    def checkSprayDelayTimeout(self):
        if self.runTimeCounter - self.lastSprayTime >= self.sprayPeriod:
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
        self.runTimeCounter = utime.ticks_diff(utime.ticks_ms(), self.bootTickMs) // 1000
        self.readSystemSensor()
        log( "[{}]Atomizer FSM status:{},fineTemp:{},tempThd:{},humi:{},TS:{},Spray count:{},AC status:{}".format(self.runTimeCounter, self.status, self.finTemp, self.fineLThreshold, self.humity, self.wetBulbTemp, self.totalSprayCount, self.airConditionerStatus))

        if (self.runTimeCounter % 3600) == 0:
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
