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
        self.runTimeCounter = 0

        self.totalSprayCount = 0
        if db.get("totalSprayCount") is not None:
            self.totalSprayCount = int(db.get("totalSprayCount"))
        else:
            db.save({"totalSprayCount":str(self.totalSprayCount)})

        self.pwmFreq = self.config["pwm1freq"]
        self.pwmMinDuty = self.config["pwm1min"]
        self.pwmMaxDuty = self.config["pwm1max"]

        self.lastSprayTime = 0
        self.sprayPeriod = self.config["sprayPeriod"]
        self.minSparyTime = self.config["minSparyTime"]
        
        self.spray1StartTime = 0
        self.spray1TimeOut = 5

        self.spray2StartTime = 0
        self.spray2TimeOut = 5

        self.spray3StartTime = 0
        self.spray3TimeOut = 0


        self.finTemp = 0
        self.humity = 0
        self.wetBulbTemp = 0
        self.fineLThreshold = self.config["fineLThreshold"]
        self.fineHThreshold = self.config["fineHThreshold"]
    
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
        print("reload config:{}".format(self.config))
        self.pwmFreq = int(self.config["pwm1freq"])
        self.pwmMinDuty = int(self.config["pwm1min"])
        self.pwmMaxDuty = int(self.config["pwm1max"])
        self.sprayPeriod = int(self.config["sprayPeriod"])
        self.minSparyTime = int(self.config["minSparyTime"])
        self.fineLThreshold = float(self.config["fineLThreshold"])
        self.fineHThreshold = float(self.config["fineHThreshold"])

    def close(self):
        print("Atomizer FSM:close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkWaterMark(self):
        #初始化所有执行器
        self.setDeviceToReadyStatus()

        if enum.WaterMark.NORMAL == self.bspInstance.getWaterTankStatus() or enum.WaterMark.FULL == self.bspInstance.getWaterTankStatus():
            self.status = STATUS.WATER_TANK_OK
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif (self.lastAddWaterTime != 0) and (self.runTimeCounter - self.lastAddWaterTime < self.addWaterMinInterval):
            print("[ERROR]can not add water too frequent.last:{},now:{},interval:{}".format(self.lastAddWaterTime,
                                                                                            self.runTimeCounter,
                                                                                            self.addWaterMinInterval))
            self.status = STATUS.READY
        else:
            self.status = STATUS.WATER_TANK_NOT_OK
            # 启动排废水
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.ON)
            #bsp.setEV(enum.EV.WATER_INPUT_EV, 0)#-->转移到self.setDeviceToReadyStatus()
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.waterDischargeStartTime = self.runTimeCounter

    def checkAirConditionerStatus(self):
        if self.airConditionerStatus == enum.Switch.ON:
            self.status = STATUS.AIR_CONDITIONER_ON
        else:
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.status = STATUS.READY

    def checkOverTemperature(self):
        if self.bspInstance.getWaterAvailableStatus() == False:
            print("[ERROR]Water inavailable.")
            self.status = STATUS.READY
        elif self.finTemp > self.fineLThreshold:
            self.status = STATUS.OVER_TEMP
            self.lastOverTempTime = self.runTimeCounter
            self.totalSprayCount += 1
            self.saveData()
            # 根据温度计算额外喷雾时间: >38+1s, >39+2s, >40+3s, >41+4s
            extra = 0
            if self.finTemp > 41:
                extra = 4
            elif self.finTemp > 40:
                extra = 3
            elif self.finTemp > 39:
                extra = 2
            elif self.finTemp > 38:
                extra = 1
            self.spray1TimeOut = self.minSparyTime + extra
            self.spray2TimeOut = self.spray1TimeOut
            print("over temp, need spray {}s.".format(self.spray1TimeOut))
        else:
            self.status = STATUS.READY

    def openPump(self):
        self.bspInstance.setWaterPump(100)

    def closePump(self):
        self.bspInstance.setWaterPump(0)

    def openSparyEV1(self):
        print("spray 1...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.ON)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.spray1StartTime = self.runTimeCounter

    def openSparyEV2(self):
        print("spray 2...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.ON)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.OFF)
        self.spray2StartTime = self.runTimeCounter

    def openSparyEV3(self):
        print("spray 3...............")
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_1, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_2, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_SPRAY_EV_3, enum.Switch.ON)  #暂时没有这个电磁阀
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
            print("spray 1 finish.")
            self.status = STATUS.SPRAY_WATER_2
            self.openPump()
            self.openSparyEV2()
        else:
            return

    def checkSpray2Timeout(self):
        if self.runTimeCounter - self.spray2StartTime >= self.spray2TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            print("spray 2 finish.")
            self.status = STATUS.SPRAY_WATER_3
            #self.openPump() 暂时没有这个电磁阀
            #self.openSparyEV3()
            self.closeAllSparyEV()
            self.closePump()
        else:
            return

    def checkSpray3Timeout(self):
        if self.runTimeCounter - self.spray3StartTime >= self.spray3TimeOut:
            # 关闭喷水设备，或者在READY里处理此设备
            print("spray 3 finish.")
            self.closeAllSparyEV()
            self.closePump()
            self.lastSprayTime = self.runTimeCounter
            self.status = STATUS.SPRAY_DELAY
        else:
            return

    def checkSprayDelayTimeout(self):
        if self.runTimeCounter - self.lastSprayTime >= self.sprayPeriod:
            print("spray delay finish.")
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
        print("[WARN]Atomizer FSM:close all executor.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.READY
        return
    
    def run(self):
        self.runTimeCounter = utime.time()
        self.readSystemSensor()
        print( "[{}]Atomizer FSM status:{},fineTemp:{},tempThd:{},humi:{},TS:{},Spray count:{},AC status:{}".format(self.runTimeCounter, self.status, self.finTemp, self.fineLThreshold, self.humity, self.wetBulbTemp, self.totalSprayCount, self.airConditionerStatus))

        if (self.runTimeCounter % 3600) == 0:
            self.saveData()
            print("AM FSM:save data to db finish.")


        func = self.switch.get(self.status, lambda: print("Atomizer FSM:status not define."))
        return func()

# if __name__=="__main__":
#     fsm = FSM()
#
#     for i in range(50):
#         print("[tick]:{}".format(fsm.timeCounter))
#         fsm.timeCounter = i
#         fsm.run()
