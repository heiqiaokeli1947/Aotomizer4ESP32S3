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
        self.FSMRunCounter = 0
        self.startTime = utime.time()
        self.runTimeCounter = 0
        self.totalRunTime = 0
        if db.get("totalRunTime") is not None:
            self.totalRunTime = int(db.get("totalRunTime"))
        else:
            db.save({"totalRunTime":str(self.totalRunTime)})

        self.totalSprayCount = 0
        if db.get("totalSprayCount") is not None:
            self.totalSprayCount = int(db.get("totalSprayCount"))
        else:
            db.save({"totalSprayCount":str(self.totalSprayCount)})

        self.pwmFreq = 25000
        if db.get("pwmFreq") is not None:
            self.pwmFreq = int(db.get("pwmFreq"))
        else:
            db.save({"pwmFreq":str(self.pwmFreq)})

        self.pwmMinDuty = 15
        if db.get("pwmMinDuty") is not None:
            self.pwmMinDuty = int(db.get("pwmMinDuty"))
        else:
            db.save({"pwmMinDuty":str(self.pwmMinDuty)})

        self.pwmMaxDuty = 95
        if db.get("pwmMaxDuty") is not None:
            self.pwmMaxDuty = int(db.get("pwmMaxDuty"))
        else:
            db.save({"pwmMaxDuty":str(self.pwmMaxDuty)})

        self.lastSprayTime = 0
        self.sprayPeriod = 40
        if db.get("sprayPeriod") is not None:
            self.sprayPeriod = int(db.get("sprayPeriod"))
        else:
            db.save({"sprayPeriod":str(self.sprayPeriod)})

        self.minSparyTime = 3
        if db.get("minSparyTime") is not None:
            self.minSparyTime = int(db.get("minSparyTime"))
        else:
            db.save({"minSparyTime":str(self.minSparyTime)})
        
        self.spray1StartTime = 0
        self.spray1TimeOut = 5

        self.spray2StartTime = 0
        self.spray2TimeOut = 5

        self.spray3StartTime = 0
        self.spray3TimeOut = 0


        self.finTemp = 0
        self.humity = 0
        self.wetBulbTemp = 0
        self.fineLThreshold = 37.5
        if db.get("fineLThreshold") is not None:
            self.fineLThreshold = float(db.get("fineLThreshold"))
        else:
            db.save({"fineLThreshold":str(self.fineLThreshold)})

        self.fineHThreshold = 42.0
        if db.get("fineHThreshold") is not None:
            self.fineHThreshold = float(db.get("fineHThreshold"))
        else:
            db.save({"fineHThreshold":str(self.fineHThreshold)})

        self.roomTemp = 0
        self.roomTempThreshold = 32

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
               "totalRunTime":self.totalRunTime,
               "fineTempThreshold":self.fineLThreshold,
               "fineTemp":self.finTemp,
               "airConditionerStatus":self.airConditionerStatus,
               "pwmFreq":self.pwmFreq,
               "pwmMinDuty":self.pwmMinDuty,
               "pwmMaxDuty":self.pwmMaxDuty,
               "sprayPeriod":self.sprayPeriod,
               "minSparyTime":self.minSparyTime,
               "fineLThreshold":self.fineLThreshold,
               "fineHThreshold":self.fineHThreshold}

    def saveData(self):
        db.save({"totalSprayCount":str(self.totalSprayCount),
                 "totalRunTime":str(self.totalRunTime),
                 "pwmFreq":str(self.pwmFreq),
                 "pwmMinDuty":str(self.pwmMinDuty),
                 "pwmMaxDuty":str(self.pwmMaxDuty),
                 "sprayPeriod":str(self.sprayPeriod),
                 "minSparyTime":str(self.minSparyTime),
                 "fineLThreshold":str(self.fineLThreshold),
                 "fineHThreshold":str(self.fineHThreshold)})

    def reloadConfig(self):
        res = db.multiGet(["pwmFreq","pwmMinDuty","pwmMaxDuty","sprayPeriod","minSparyTime","fineLThreshold","fineHThreshold"])
        print("reload config:{}".format(res))
        self.pwmFreq = int(res["pwmFreq"])
        self.pwmMinDuty = int(res["pwmMinDuty"])
        self.pwmMaxDuty = int(res["pwmMaxDuty"])
        self.sprayPeriod = int(res["sprayPeriod"])
        self.minSparyTime = int(res["minSparyTime"])
        self.fineLThreshold = float(res["fineLThreshold"])
        self.fineHThreshold = float(res["fineHThreshold"])

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

    def checkWaterTankFillTimeout(self):
        if self.runTimeCounter - self.waterFillStartTime >= self.waterFillTimeOut:
            #补水超时故障
            print("[ERROR]fill water time out.")
            self.lastAddWaterTime = self.runTimeCounter
            self.status = STATUS.READY
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif self.waterMark == enum.WaterMark.FULL:
            #关闭补水设备，或者在READY里处理此设备
            print("[OK]fill water to full success")
            self.lastAddWaterTime = self.runTimeCounter
            self.addWaterCount += 1
            self.status = STATUS.READY
            # 关闭排水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 可以依赖Ready状态的设置，放这里是为了快速响应
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.OFF)
        else:  #未超时，继续补水
            print("continue fill water.{}".format(self.waterFillTimeOut - (self.runTimeCounter - self.waterFillStartTime)))
            return

    def checkWaterDischargeTimeout(self):
        if self.runTimeCounter - self.waterDischargeStartTime >= self.waterDischargeTimeOut:
            #排废水完成
            print("water discharge finish.")
            self.status = STATUS.WATER_DISCHARGE_OK
            # 启动进水
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.ON)
            self.waterFillStartTime = self.runTimeCounter
        else:  #未超时，继续排废水
            print("continue discharge water.{}".format(
                self.waterDischargeTimeOut - (self.runTimeCounter - self.waterDischargeStartTime)))
            return

    def checkOverTemperature(self):
        if self.finTemp > self.fineLThreshold:
            self.status = STATUS.OVER_TEMP
            self.lastOverTempTime = self.runTimeCounter
            self.totalSprayCount += 1
            if self.finTemp > 41:
                self.spray1TimeOut = self.minSparyTime+4
                self.spray2TimeOut = self.minSparyTime+4
            elif self.finTemp > 40:
                self.spray1TimeOut = self.minSparyTime+3
                self.spray2TimeOut = self.minSparyTime+3
            elif self.finTemp > 39:
                self.spray1TimeOut = self.minSparyTime+2
                self.spray2TimeOut = self.minSparyTime+2
            elif self.finTemp > 38:
                self.spray1TimeOut = self.minSparyTime+1
                self.spray2TimeOut = self.minSparyTime+1
            else:
                self.spray1TimeOut = self.minSparyTime
                self.spray2TimeOut = self.minSparyTime
            print("over temp, need spray {}s.".format(self.spray1TimeOut))
        else:
            #print("not over temp.")
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
        self.roomTemp = self.bspInstance.getSensorData().tempBMP280

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
        self.totalRunTime += (self.runTimeCounter - self.startTime)
        self.startTime = self.runTimeCounter

        self.FSMRunCounter += 1
        self.readSystemSensor()
        print( "[{}]Atomizer FSM status:{},fineTemp:{},threshold:{},humi:{},wet buld temp:{},Run times:{},Spray count:{},AC status:{}".format(self.runTimeCounter, self.status, self.finTemp, self.fineLThreshold, self.humity, self.wetBulbTemp, self.totalRunTime, self.totalSprayCount, self.airConditionerStatus))

        if (self.FSMRunCounter % 3600) == 0:
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
