import utime
import driver.enum as enum
import domain.DBUtils as db



class STATUS:
    INIT = 0
    READY = 1
    WATER_TANK_NOT_OK = 2
    WATER_DISCHARGE_OK = 3

class FSM:
    def __init__(self,bspInstance,config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT
        self.runTimeCounter = 0

        # 1=空 2=正常 3=满
        self.waterMark = enum.WaterMark.FULL
        self.waterDischargeStartTime = 0
        self.waterFillStartTime = 0
        self.waterAvailable = False
        # 约365s从刚下到低水位加到高水位
        self.waterFillTimeOut = self.config["waterFillTimeOut"]
        self.waterDischargeTimeOut = self.config["waterDischargeTimeOut"] #55s=2L
        self.minAddWaterInterval = self.config["minAddWaterInterval"]
        
        self.totalAddWaterCount = 0
        if db.get("totalAddWaterCount") is not None:
            self.totalAddWaterCount = int(db.get("totalAddWaterCount"))
        else:
            db.save({"totalAddWaterCount":str(self.totalAddWaterCount)})
        
        self.lastAddWaterTime = 0
        self.airConditionerStatus = 0

        self.inWaterTDS = 0
        self.waterTankTDS = 0
        self.waterTDSThreshold = self.config["waterTDSThreshold"]
        

        self.switch = {STATUS.INIT: self.initDevice,
                       STATUS.READY: self.checkWaterMark,
                       STATUS.WATER_TANK_NOT_OK: self.checkWaterDischargeTimeout,
                       STATUS.WATER_DISCHARGE_OK: self.checkWaterTankFillTimeout}
        
    def setConfig(self,config):
        self.config = config

    #只需要反馈sysConfig里没有的参数，也就是实时变化的参数
    def getStatus(self):
        return {"totalAddWaterCount":self.totalAddWaterCount,
                "waterMark":self.waterMark,
                "inWaterTDS":self.inWaterTDS,
                "waterTankTDS":self.waterTankTDS,
                "waterAvailable":self.waterAvailable}

    def saveData(self):
        db.save({"totalAddWaterCount":str(self.totalAddWaterCount)})

    def reloadConfig(self):
        self.minAddWaterInterval = int(self.config["minAddWaterInterval"])
        self.waterTDSThreshold = int(self.config["waterTDSThreshold"])
        self.waterFillTimeOut = int(self.config["waterFillTimeOut"])
        self.waterDischargeTimeOut = int(self.config["waterDischargeTimeOut"]) #55s=2L


    def close(self):
        print("Water process FSM:close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkWaterMark(self):
        #初始化所有执行器
        self.setDeviceToReadyStatus()

        #检查水质
        if self.waterTankTDS < self.waterTDSThreshold:
            self.waterAvailable = True
        else:
            self.waterAvailable = False

        if enum.WaterMark.NORMAL == self.bspInstance.getWaterTankStatus() or enum.WaterMark.FULL == self.bspInstance.getWaterTankStatus():
            self.status = STATUS.READY
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif (self.lastAddWaterTime != 0) and (self.runTimeCounter - self.lastAddWaterTime < self.minAddWaterInterval):
            print("[WARN]can not add water too frequent.last:{},now:{},interval:{}".format(self.lastAddWaterTime,
                                                                                            self.runTimeCounter,
                                                                                            self.minAddWaterInterval))
            self.status = STATUS.READY
        else:
            self.status = STATUS.WATER_TANK_NOT_OK
            # 启动排废水
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.ON)
            #bsp.setEV(enumEV.enumEV.WATER_INPUT_EV, 0)#-->转移到self.setDeviceToReadyStatus()
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.waterDischargeStartTime = self.runTimeCounter

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
            self.totalAddWaterCount += 1
            self.saveData()
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
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.ON)
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
            self.waterFillStartTime = self.runTimeCounter
        else:  #未超时，继续排废水
            print("continue discharge water.{}".format(
                self.waterDischargeTimeOut - (self.runTimeCounter - self.waterDischargeStartTime)))
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
        self.runTimeCounter = utime.time()
        self.readSystemSensor()
        print( "[{}]Water process FSM status:{},water mark:{},AC status:{},Add water count:{}".format(self.runTimeCounter, self.status, self.waterMark, self.airConditionerStatus, self.totalAddWaterCount))

        if (self.runTimeCounter % 3600) == 0:
            self.saveData()
            print("WP FSM:save data to db finish.")

        func = self.switch.get(self.status, lambda: print("Water process FSM:status not define."))
        return func()

# if __name__=="__main__":
#     fsm = FSM()
#
#     for i in range(50):
#         print("[tick]:{}".format(fsm.runTimeCounter))
#         fsm.runTimeCounter = i
#         fsm.run()
