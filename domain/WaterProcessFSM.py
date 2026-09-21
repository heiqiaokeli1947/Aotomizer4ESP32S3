from domain.LogUtils import log
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
        # runTimeCounterMs 为开机以来的单调毫秒数（RTC 时基 ticks_ms 节拍差），
        # 与墙钟解耦（NTP 跳变不影响），且与 FSM 轮询频率解耦（10Hz 节拍，2026-09-21）
        self.bootTickMs = utime.ticks_ms()
        self.runTimeCounterMs = 0
        self.lastLogMs = 0   # 状态日志节流起点（每 1s 打印一次）
        self.lastSaveMs = 0  # "每小时落盘一次"时间边沿判定起点

        # 1=空 2=正常 3=满
        self.waterMark = enum.WaterMark.FULL
        self.waterDischargeStartTime = 0
        self.waterFillStartTime = 0
        # 约365s从刚下到低水位加到高水位
        # 超时配置单位为秒，内部统一毫秒计时（10Hz 节拍）
        self.waterFillTimeOut = int(self.config["waterFillTimeOut"]) * 1000
        self.waterDischargeTimeOut = int(self.config["waterDischargeTimeOut"]) * 1000
        self.minAddWaterInterval = int(self.config["minAddWaterInterval"]) * 1000
        self.waterTDSThreshold = int(self.config["waterTDSThreshold"])
        
        self.totalAddWaterCount = 0
        if db.get("totalAddWaterCount") is not None:
            self.totalAddWaterCount = int(db.get("totalAddWaterCount"))
        else:
            db.save({"totalAddWaterCount":str(self.totalAddWaterCount)})
        
        self.lastAddWaterTime = 0

        self.airConditionerStatus = 0
        self.inWaterTDS = 0
        self.inWaterTemp = 0
        self.waterTankTDS = 0
        self.waterTankTemp = 0
        self.waterAvailable = False
        

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
                "inWaterTemp":self.inWaterTemp,
                "waterTankTDS":self.waterTankTDS,   
                "waterAvailable":self.waterAvailable,
                "waterTankTemp":self.waterTankTemp,
                "waterTDSThreshold":self.waterTDSThreshold}

    def saveData(self):
        db.save({"totalAddWaterCount":str(self.totalAddWaterCount)})

    def reloadConfig(self):
        self.minAddWaterInterval = int(self.config["minAddWaterInterval"])
        self.waterFillTimeOut = int(self.config["waterFillTimeOut"])
        self.waterDischargeTimeOut = int(self.config["waterDischargeTimeOut"])
        self.waterTDSThreshold = int(self.config["waterTDSThreshold"])


    def close(self):
        log("Water process FSM:close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkWaterMark(self):
        #初始化所有执行器
        self.setDeviceToReadyStatus()

        if enum.WaterMark.NORMAL == self.bspInstance.getWaterTankStatus() or enum.WaterMark.FULL == self.bspInstance.getWaterTankStatus():
            self.status = STATUS.READY
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif (self.lastAddWaterTime != 0) and (self.runTimeCounterMs - self.lastAddWaterTime < self.minAddWaterInterval):
            log("[WARN]can not add water too frequent.last:{},now:{},interval:{}".format(self.lastAddWaterTime,
                                                                                            self.runTimeCounterMs,
                                                                                            self.minAddWaterInterval))
            self.status = STATUS.READY
        else:
            self.status = STATUS.WATER_TANK_NOT_OK
            # 启动排废水
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.ON)
            #bsp.setEV(enumEV.enumEV.WATER_INPUT_EV, 0)#-->转移到self.setDeviceToReadyStatus()
            # 关闭所有喷水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 关闭水泵-->转移到self.setDeviceToReadyStatus()
            self.waterDischargeStartTime = self.runTimeCounterMs

    def checkWaterTankFillTimeout(self):
        if self.runTimeCounterMs - self.waterFillStartTime >= self.waterFillTimeOut:
            #补水超时故障
            log("[ERROR]fill water time out.")
            self.lastAddWaterTime = self.runTimeCounterMs
            self.status = STATUS.READY
            # 关闭排水/进水电磁阀-->转移到self.setDeviceToReadyStatus()
        elif self.waterMark == enum.WaterMark.FULL:
            #关闭补水设备，或者在READY里处理此设备
            log("[OK]fill water to full success")
            self.lastAddWaterTime = self.runTimeCounterMs
            self.totalAddWaterCount += 1
            self.saveData()
            self.status = STATUS.READY
            # 关闭排水电磁阀-->转移到self.setDeviceToReadyStatus()
            # 可以依赖Ready状态的设置，放这里是为了快速响应
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.OFF)
        else:  #未超时，继续补水
            log("continue fill water.{}ms".format(self.waterFillTimeOut - (self.runTimeCounterMs - self.waterFillStartTime)))
            return

    def checkWaterDischargeTimeout(self):
        if self.runTimeCounterMs - self.waterDischargeStartTime >= self.waterDischargeTimeOut:
            #排废水完成
            log("water discharge finish.")
            self.status = STATUS.WATER_DISCHARGE_OK
            # 启动进水
            self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.ON)
            self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
            self.waterFillStartTime = self.runTimeCounterMs
        else:  #未超时，继续排废水
            log("continue discharge water.{}ms".format(
                self.waterDischargeTimeOut - (self.runTimeCounterMs - self.waterDischargeStartTime)))
            return

    def getWaterParam(self):
        self.inWaterTDS = self.bspInstance.getSensorData().inWaterTDS
        self.inWaterTemp = self.bspInstance.getSensorData().inWaterTemp
        self.waterTankTDS = self.bspInstance.getSensorData().waterTankTDS
        self.waterTankTemp = self.bspInstance.getSensorData().waterTankTemp
        self.waterAvailable = self.bspInstance.getWaterAvailableStatus()
        self.waterMark = self.bspInstance.getWaterTankStatus()

    def getAirConditonerStatus(self):
        self.airConditionerStatus = self.bspInstance.getAirconditionerStatus()

    def readSystemSensor(self):
        self.getWaterParam()
        self.getAirConditonerStatus()

    def setDeviceToReadyStatus(self):
        self.bspInstance.setEV(enum.EV.WASTE_WATER_EV, enum.Switch.OFF)
        self.bspInstance.setEV(enum.EV.WATER_INPUT_EV, enum.Switch.OFF)
        #bsp.setWaterProcessorPump(0)

    def initDevice(self):
        # 初始化设备
        log("[WARN]Water process FSM:close all executor.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.READY
        return
    
    def run(self):
        self.runTimeCounterMs = utime.ticks_diff(utime.ticks_ms(), self.bootTickMs)
        self.readSystemSensor()
        # 状态日志节流为每 1s 一次（10Hz 轮询，避免日志刷屏）
        if self.runTimeCounterMs - self.lastLogMs >= 1000:
            self.lastLogMs = self.runTimeCounterMs
            log( "[{}]Water process FSM status:{},water mark:{},AC status:{},Add water count:{}".format(self.runTimeCounterMs // 1000, self.status, self.waterMark, self.airConditionerStatus, self.totalAddWaterCount))

        # 每小时落盘一次（时间边沿触发，与轮询频率解耦）
        if self.runTimeCounterMs - self.lastSaveMs >= 3600 * 1000:
            self.lastSaveMs = self.runTimeCounterMs
            self.saveData()
            log("WP FSM:save data to db finish.")

        func = self.switch.get(self.status, lambda: log("Water process FSM:status not define."))
        return func()

# if __name__=="__main__":
#     fsm = FSM()
#
#     for i in range(50):
#         log("[tick]:{}".format(fsm.runTimeCounter))
#         fsm.runTimeCounter = i
#         fsm.run()
