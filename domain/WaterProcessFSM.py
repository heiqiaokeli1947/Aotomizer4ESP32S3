import utime
import driver.enum as enum
import domain.DBUtils as db



class STATUS:
    INIT = 0
    READY = 1
    WATER_TANK_OK = 2
    WATER_TANK_NOT_OK = 3
    WATER_DISCHARGE_OK = 4

class FSM:
    def __init__(self,bspInstance,config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT
        self.FSMRunCounter = 0
        self.timeCounter = 0

        self.waterMark = enum.WaterMark.FULL
        # 1=空 2=正常 3=满
        self.waterMarkThreshold = 1

        self.waterFillStartTime = 0

        # 约365s从刚下到低水位加到高水位
        self.waterFillTimeOut = 850
        if db.get("waterFillTimeOut") is not None:
            self.waterFillTimeOut = int(db.get("waterFillTimeOut"))
        else:
            db.save({"waterFillTimeOut":str(self.waterFillTimeOut)})

        self.waterDischargeStartTime = 0
        self.waterDischargeTimeOut = 60 #55s=2L
        if db.get("waterDischargeTimeOut") is not None:
            self.waterDischargeTimeOut = int(db.get("waterDischargeTimeOut"))
        else:
            db.save({"waterDischargeTimeOut":str(self.waterDischargeTimeOut)})

        self.totalAddWaterCount = 0
        if db.get("totalAddWaterCount") is not None:
            self.totalAddWaterCount = int(db.get("totalAddWaterCount"))
        else:
            db.save({"totalAddWaterCount":str(self.totalAddWaterCount)})

        self.minAddWaterInterval = 2400
        if db.get("minAddWaterInterval") is not None:
            self.minAddWaterInterval = int(db.get("minAddWaterInterval"))
        else:
            db.save({"minAddWaterInterval":str(self.minAddWaterInterval)})
        
        self.lastAddWaterTime = 0
        

        self.airConditionerStatus = 0

        self.inWaterTDS = 0
        self.waterTankTDS = 0

        self.waterTDSThreshold = 20
        if db.get("waterTDSThreshold") is not None:
            self.waterTDSThreshold = int(db.get("waterTDSThreshold"))
        else:
            db.save({"waterTDSThreshold":str(self.waterTDSThreshold)})

        self.switch = {STATUS.INIT: self.initDevice,
                       STATUS.READY: self.checkWaterMark,
                       STATUS.WATER_TANK_OK: self.checkAirConditionerStatus,
                       STATUS.WATER_TANK_NOT_OK: self.checkWaterDischargeTimeout,
                       STATUS.WATER_DISCHARGE_OK: self.checkWaterTankFillTimeout}
        
    def setConfig(self,config):
        self.config = config

    def getStatus(self):
        return {"airConditionerStatus":self.airConditionerStatus,
                "minAddWaterInterval":self.minAddWaterInterval,
                "totalAddWaterCount":self.totalAddWaterCount,
                "waterTDSThreshold":self.waterTDSThreshold,
                "waterMark":self.waterMark}

    def saveData(self):
        db.save({"minAddWaterInterval":str(self.minAddWaterInterval),"totalAddWaterCount":str(self.totalAddWaterCount)})

    def reloadConfig(self):
        res = db.multiGet(["minAddWaterInterval","waterTDSThreshold"])
        print("reload config:{}".format(res))
        self.minAddWaterInterval = int(res["minAddWaterInterval"])
        self.waterTDSThreshold = int(res["waterTDSThreshold"])

    def close(self):
        print("Water process FSM:close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkWaterMark(self):
        #初始化所有执行器
        self.setDeviceToReadyStatus()

        if enum.WaterMark.NORMAL == self.bspInstance.getWaterTankStatus() or enum.WaterMark.FULL == self.bspInstance.getWaterTankStatus():
            self.status = STATUS.WATER_TANK_OK
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif (self.lastAddWaterTime != 0) and (self.timeCounter - self.lastAddWaterTime < self.minAddWaterInterval):
            print("[ERROR]can not add water too frequent.last:{},now:{},interval:{}".format(self.lastAddWaterTime,
                                                                                            self.timeCounter,
                                                                                            self.minAddWaterInterval))
            self.status = STATUS.READY
        else:
            self.status = STATUS.WATER_TANK_NOT_OK
            # 启动排废水
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.ON)
            #bsp.setEV(enumEV.enumEV.WATER_INPUT_EV, 0)#-->转移到self.setDeviceToReadyStatus()
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.waterDischargeStartTime = self.timeCounter

    def checkAirConditionerStatus(self):
        if self.airConditionerStatus == True:
            pass
        #print("AirConditoner stauts:{}".format(self.airConditionerStatus))
        # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
        # 关闭水泵-->转移到self.setDeviceToReadyStatus()
        self.status = STATUS.READY

    def checkWaterTankFillTimeout(self):
        if self.timeCounter - self.waterFillStartTime >= self.waterFillTimeOut:
            #补水超时故障
            print("[ERROR]fill water time out.")
            self.lastAddWaterTime = self.timeCounter
            self.status = STATUS.READY
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif self.waterMark == enum.WaterMark.FULL:
            #关闭补水设备，或者在READY里处理此设备
            print("[OK]fill water to full success")
            self.lastAddWaterTime = self.timeCounter
            self.totalAddWaterCount += 1
            self.status = STATUS.READY
            # 关闭排水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 可以依赖Ready状态的设置，放这里是为了快速响应
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.OFF)
        else:  #未超时，继续补水
            print("continue fill water.{}".format(self.waterFillTimeOut - (self.timeCounter - self.waterFillStartTime)))
            return

    def checkWaterDischargeTimeout(self):
        if self.timeCounter - self.waterDischargeStartTime >= self.waterDischargeTimeOut:
            #排废水完成
            print("water discharge finish.")
            self.status = STATUS.WATER_DISCHARGE_OK
            # 启动进水
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.ON)
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
            self.waterFillStartTime = self.timeCounter
        else:  #未超时，继续排废水
            print("continue discharge water.{}".format(
                self.waterDischargeTimeOut - (self.timeCounter - self.waterDischargeStartTime)))
            return

    def getWaterTDS(self):
        self.inWaterTDS = 0
        self.waterTankTDS = 0

    def getWaterMark(self):
        self.waterMark = self.bspInstance.getWaterTankStatus()

    def getAirConditonerStatus(self):
        self.airConditionerStatus = self.bspInstance.getAirconditionerStatus()

    def readSystemSensor(self):
        self.getWaterTDS()
        self.getWaterMark()
        self.getAirConditonerStatus()

    def setDeviceToReadyStatus(self):
        self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.OFF)
        #bsp.setWaterProcessorPump(0)

    def initDevice(self):
        # 初始化设备
        print("[WARN]Water process FSM:close all executor.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.READY
        return
    
    def run(self):
        self.timeCounter = utime.time()
        self.FSMRunCounter += 1
        self.readSystemSensor()
        print( "[{}]Water process FSM status:{},water mark:{},AC status:{},Add water count:{}".format(self.timeCounter, self.status, self.waterMark, self.airConditionerStatus, self.totalAddWaterCount))

        if (self.FSMRunCounter % 3600) == 0:
            self.saveData()
            print("WP FSM:save data to db finish.")

        func = self.switch.get(self.status, lambda: print("Water process FSM:status not define."))
        return func()

# if __name__=="__main__":
#     fsm = FSM()
#
#     for i in range(50):
#         print("[tick]:{}".format(fsm.timeCounter))
#         fsm.timeCounter = i
#         fsm.run()
