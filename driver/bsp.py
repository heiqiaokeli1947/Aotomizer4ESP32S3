from domain.LogUtils import log
from machine import Pin, PWM, I2C, SoftI2C, Timer
from micropython import const
import domain.sensorData as sensorData
import neopixel
import driver.bmp280 as bmp280
import driver.hdc1080 as hdc1080
from driver.tds import TDSModule as tds
import driver.enum as enum
import domain.AACOps as AAC

_WATER_PUMP_FREQ = const(1000)
_WATER_PUMP_DEFAULT_PERCENT = const(0)

class BSP:
    # 单例实例
    __instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super(BSP, cls).__new__(cls)
            # 延迟初始化，在第一次调用时完成
            cls.__instance._initialized = False
        return cls.__instance
    
    def __init__(self):
        # 防止重复初始化
        if self._initialized:
            log("BSP initialed.")
            return

        log("BSP Initializing...")
        self.config = None

        #软件I2C
        self.softI2C = SoftI2C(scl=Pin(3), sda=Pin(8), freq=100000)
        # WS2812
        self.__LEDArray = neopixel.NeoPixel(Pin(48), 1)

        # 雾化泵PWM控制
        self.__pwmWaterBump = None
		# 预留喷水泵PWM控制 Pin(11)
        # 雾化电磁阀1
        self.__sprayEV1 = Pin(11, Pin.OUT, value=0)
        # 雾化电磁阀2
        self.__sprayEV2 = Pin(12, Pin.OUT, value=0)
        # 雾化电磁阀3
        self.__sprayEV3 = Pin(13, Pin.OUT, value=0)

        # 进水电磁阀
        self.__waterInEV = Pin(14, Pin.OUT, value=0)
        # 废水电磁阀
        self.__wasteWaterEV = Pin(21, Pin.OUT, value=0)
        # 34及以上，无上下拉，需要外置
		# 水箱水位上传感器
        self.__waterTankTopSensor = Pin(15, Pin.IN, Pin.PULL_UP) #必须上拉，线路断开时有保护作用。
    	# 水箱水位下传感器
        self.__waterTankBottomSensor = Pin(16, Pin.IN, Pin.PULL_UP) #需要硬件上拉,低水位是低电平，线路断开时则认为不是低水位，有保护作用。
        self.__sysEnableSwitch = Pin(4, Pin.IN, Pin.PULL_DOWN)  #ESP32S3引脚范围0~21、26~48，所以修改23->5
        self.__sprayEnableSwitch = Pin(5, Pin.IN, Pin.PULL_DOWN)  #ESP32S3引脚范围0~21、26~48，所以修改34->6
        self.__airconditionerForceEn = Pin(6, Pin.IN, Pin.PULL_DOWN)  # ESP32S3引脚范围0~21、26~48，所以修改34->7
        self.__airconditionerHallSensor = Pin(7, Pin.IN, Pin.PULL_DOWN) #需要硬件下拉,霍尔传感器有效是高电平，线路断开时认为空调关机，有保护作用。
        # PWM控制
        self.__fanSpeed = 0
        self.__fan1PwmPin = None
        self.__fan2PwmPin = None

        #
        self.__sensorData = sensorData.SensorData()

        log("init bmp280...")
        self.__bmp280 = bmp280.BMP280(self.softI2C)

        log("init hdc1080...")
        self.__hdc1080 = hdc1080.HDC1080(self.softI2C)

        log("init tds...")
        TDS_TX_PIN = 18  # ESP32 TX -> 模块RX
        TDS_RX_PIN = 17  # ESP32 RX -> 模块TX
        # baudrate 显式指定 9600（TDS 模块固定波特率）：不依赖驱动默认值，防静默漂移
        self.tds_sensor = tds(tx_pin=TDS_TX_PIN, rx_pin=TDS_RX_PIN, uart_id=1, baudrate=9600)

        self.__sensorReadTimer = Timer(1)
        self.__sensorReadTimer.init(mode=Timer.PERIODIC, period=1000, callback=self.timerHandler)

        self.setLEDArray((255, 255, 255))
        self.aac = AAC.AACOptimized()
        
        # 标记已初始化
        self._initialized = True

        self.runCounter = 0
        self._tds_state = 0
        self._tds_channel = 0
        self._tds_inWaterTDS = -9999.0
        self._tds_inWaterTemp = -9999.0
        self._tds_waterTankTDS = -9999.0
        self._tds_waterTankTemp = -9999.0

    def setConfig(self, config):
        self.config = config
        # PWM 对象仅构造一次；参数变更只原地更新 freq/duty——
        # 原实现每次保存参数都经 initHW() 重建 3 个 PWM 对象（重复构造-丢弃循环
        # 累积待 GC 的 PWM 对象与硬件通道重绑定开销），且运行中重建会让
        # 水泵/风扇输出瞬间毛刺（2026-09-21 修复）
        if getattr(self, "_pwmReady", False):
            self.updatePWM()
        else:
            self.initHW()

    def initHW(self):
        log("init pwm...")
        self.__pwmWaterBump = PWM(Pin(10),freq=int(self.config["pwm1freq"]), duty=int(self.config["pwm1default"]))
        self.__fanSpeed = 0
        self.__fan1PwmPin = PWM(Pin(46),freq=int(self.config["pwm2freq"]), duty=int(self.config["pwm2default"]))
        self.__fan2PwmPin = PWM(Pin(9),freq=int(self.config["pwm3freq"]), duty=int(self.config["pwm3default"]))
        self._pwmReady = True

    def updatePWM(self):
        # 已构造的 PWM 仅更新频率/占空比，不重建对象。
        # 泵（pwm1）由 FSM 独占控制（setWaterPump），此处跳过——运行中保存任意配置
        # 若把泵 duty 强制回 pwm1default(0)，正在进行的喷雾相位会静默停泵（P1-5 修复）；
        # pwm1 参数变更在下次上电 initHW() 时生效
        self.__fan1PwmPin.freq(int(self.config["pwm2freq"]))
        self.__fan1PwmPin.duty(int(self.config["pwm2default"]))
        self.__fan2PwmPin.freq(int(self.config["pwm3freq"]))
        self.__fan2PwmPin.duty(int(self.config["pwm3default"]))

    def setLEDArray(self, color):
        for i in range(1):
            self.__LEDArray[i] = color
        self.__LEDArray.write()

    def bmp280TimerHandler(self, timer):
        self.__sensorData.presure = self.__bmp280.getPress()
        self.__sensorData.altitude = self.__bmp280.getAltitude()
        self.__sensorData.tempBMP280 = self.__bmp280.getTemp()
        # log("bmp280:temp={},Presure={},Altitude={}".format(temp,pres,alt))

    def hdc1080TimerHandler(self, timer):
        self.__sensorData.temp = self.__hdc1080.temperature
        self.__sensorData.humi = self.__hdc1080.humidity
        try:
            self.__sensorData.wetBulbTemp = self.aac.ts(self.__sensorData.temp, self.__sensorData.humi/100.0, 0.1)
        except Exception:
            self.__sensorData.wetBulbTemp = -9999

    def _tdsTick(self):
        tds = self.tds_sensor

        if self._tds_state == 0:
            if self.runCounter % 5 == 0:
                if tds.start_read(1):
                    self._tds_state = 1
                    self._tds_channel = 1
        elif self._tds_state == 1:
            result = tds.poll()
            if result is not None:
                self._tds_inWaterTDS = result['tds_ppm']
                self._tds_inWaterTemp = result['temp_c']
                if tds.start_read(2):
                    self._tds_state = 2
                    self._tds_channel = 2
                else:
                    self._tds_state = 3
            elif tds._state == tds._STATE_IDLE:
                self._tds_inWaterTDS = -9999.0
                self._tds_inWaterTemp = -9999.0
                self._tds_state = 3
        elif self._tds_state == 2:
            result = tds.poll()
            if result is not None:
                self._tds_waterTankTDS = result['tds_ppm']
                self._tds_waterTankTemp = result['temp_c']
                self._applyTdsResult()
                self._tds_state = 0
            elif tds._state == tds._STATE_IDLE:
                self._tds_waterTankTDS = -9999.0
                self._tds_waterTankTemp = -9999.0
                self._applyTdsResult()
                self._tds_state = 0
        elif self._tds_state == 3:
            if tds.start_read(2):
                self._tds_state = 2
                self._tds_channel = 2
            else:
                self._tds_waterTankTDS = -9999.0
                self._tds_waterTankTemp = -9999.0
                self._applyTdsResult()
                self._tds_state = 0

    def _applyTdsResult(self):
        # BE-2：失败通道不再打出 "-999.9 ℃, -9999.0 ppm" 噪声日志——
        # 两通道均失败时合并为单条 WARN；单通道失败只 WARN 失败通道，正常通道保持完整日志
        INVALID = -9999
        ch1Fail = self._tds_inWaterTDS == INVALID
        ch2Fail = self._tds_waterTankTDS == INVALID
        if ch1Fail and ch2Fail:
            log("[WARN] TDS 两通道均读取失败，已置无效值 -9999")
        else:
            if ch1Fail:
                log("[WARN] TDS 通道1(进水) 读取失败，已置无效值 -9999")
            else:
                log(f"通道1(进水):水温：{self._tds_inWaterTemp:.1f} ℃, TDS：{self._tds_inWaterTDS:.1f} ppm")
            if ch2Fail:
                log("[WARN] TDS 通道2(水箱) 读取失败，已置无效值 -9999")
            else:
                log(f"通道2(水箱):水温：{self._tds_waterTankTemp:.1f} ℃, TDS：{self._tds_waterTankTDS:.1f} ppm")
        self.__sensorData.inWaterTDS = self._tds_inWaterTDS
        self.__sensorData.inWaterTemp = self._tds_inWaterTemp
        self.__sensorData.waterTankTDS = self._tds_waterTankTDS
        self.__sensorData.waterTankTemp = self._tds_waterTankTemp

    def timerHandler(self, timer):
        self._tdsTick()
        self.bmp280TimerHandler(timer)
        self.hdc1080TimerHandler(timer)
        self.runCounter += 1

    def setFan1Pwm(self, percent):
        if percent > 100:
            percent = 100

        if percent < 0:
            percent = 0

        self.__fanSpeed = percent

        duty = 0

        if percent == 0:
            duty = 0
        else:
            base = (int(self.config["pwm3min"])/100)*int(self.config["pwm3freq"])
            full = (int(self.config["pwm3max"]) - int(self.config["pwm3min"]))/100*int(self.config["pwm3freq"])
            duty = 1023*(full * (percent / 100.0) + base) /int(self.config["pwm3freq"])
            log("base:{},full:{},duty:{}".format(base,full,int(duty)))
            if duty > int(self.config["pwm3freq"]):
                duty = int(self.config["pwm3freq"])
        #第1组用于直接控制mos，给风扇供应电源
        if duty == 0:
            self.__fan1PwmPin.duty(0)
            log("PWM duty1:{}，duty2:{}".format(0,int(duty)))
        else:
            self.__fan1PwmPin.duty(1023)
            log("PWM duty1:{}，duty2:{}".format(1023,int(duty)))
			
		#第2组用于控制风险转速
        self.__fan2PwmPin.duty(int(duty))
        
		
    def setEV(self, ev, status):
        if ev == enum.EV.WATER_INPUT_EV:
            if status == enum.Switch.ON:
                self.__waterInEV.on()
            else:
                self.__waterInEV.off()
        elif ev == enum.EV.WASTE_WATER_EV:
            if status == enum.Switch.ON:
                self.__wasteWaterEV.on()
            else:
                self.__wasteWaterEV.off()
        elif ev == enum.EV.WATER_SPRAY_EV_1:
            if status == enum.Switch.ON:
                self.__sprayEV1.on()
            else:
                self.__sprayEV1.off()
        elif ev == enum.EV.WATER_SPRAY_EV_2:
            if status == enum.Switch.ON:
                self.__sprayEV2.on()
            else:
                self.__sprayEV2.off()
        elif ev == enum.EV.WATER_SPRAY_EV_3:
            if status == enum.Switch.ON:
                self.__sprayEV3.on()
            else:
                self.__sprayEV3.off()

    def setWaterPump(self, percent):
        tmp = max(0, min(100, percent))

        duty = _WATER_PUMP_FREQ * (tmp / 100.0)

        # log("setWaterPump duty:{}".format(int(duty)))
        self.__pwmWaterBump.duty(int(duty))

    def getWaterTankStatus(self):
        if self.__waterTankTopSensor.value() == 1:
            return enum.WaterMark.FULL
        elif self.__waterTankTopSensor.value() == 0 and self.__waterTankBottomSensor.value() == 0:
            return enum.WaterMark.NORMAL
        elif self.__waterTankTopSensor.value() == 0 and self.__waterTankBottomSensor.value() == 1:
            return enum.WaterMark.EMPTY
        else:
            log("[ERROR]:default water full status.")
            return enum.WaterMark.FULL
    def getSysEnableStatus(self):
        if self.__sysEnableSwitch.value() == 1:
            return True
        else:
            return False

    def getSprayEnableStatus(self):
        if self.__sprayEnableSwitch.value() == 1:
            return True
        else:
            return False

    def getAirconditionerStatus(self):
        if self.__airconditionerHallSensor.value() == 1:
            return enum.Switch.ON
        else:
            return enum.Switch.OFF

    def getSensorData(self):
        return self.__sensorData

    def getfanSpeed(self):
        return self.__fanSpeed

    def getWaterAvailableStatus(self):
        # TDS无效值检查
        if self.__sensorData.waterTankTDS == -9999:
            return False
        return self.__sensorData.waterTankTDS < int(self.config["waterTDSThreshold"])
    
    @classmethod
    def getInstance(cls):
        """获取单例实例"""
        if cls.__instance is None:
            cls.__instance = BSP()
        return cls.__instance
