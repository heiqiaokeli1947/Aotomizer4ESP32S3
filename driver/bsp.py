from machine import Pin, PWM, I2C, SoftI2C, Timer
from micropython import const
import domain.sensorData as sensorData
import neopixel

import driver.bmp280 as bmp280
import driver.hdc1080 as hdc1080

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
            print("BSP initialed.")
            return

        print("BSP Initializing...")
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

        print("init bmp280...")
        self.__bmp280 = bmp280.BMP280(self.softI2C)

        print("init hdc1080...")
        self.__hdc1080 = hdc1080.HDC1080(self.softI2C)

        self.__sensorReadTimer = Timer(1)
        self.__sensorReadTimer.init(mode=Timer.PERIODIC, period=1000, callback=self.timerHandler)

        self.setLEDArray((255, 255, 255))
        self.aac = AAC.AACOptimized()
        
        # 标记已初始化
        self._initialized = True

    def setConfig(self, config):
        self.config = config
        self.initHW()

    def initHW(self):
        print("init pwm...")
        self.__pwmWaterBump = PWM(Pin(10),freq=self.config["pwm1freq"], duty=self.config["pwm1default"])
        self.__fanSpeed = 0
        self.__fan1PwmPin = PWM(Pin(46),freq=self.config["pwm2freq"], duty=self.config["pwm2default"])
        self.__fan2PwmPin = PWM(Pin(9),freq=self.config["pwm3freq"], duty=self.config["pwm3default"])

    def setLEDArray(self, color):
        for i in range(1):
            self.__LEDArray[i] = color
        self.__LEDArray.write()

    def bmp280TimerHandler(self, timer):
        self.__sensorData.presure = self.__bmp280.getPress()
        self.__sensorData.altitude = self.__bmp280.getAltitude()
        self.__sensorData.tempBMP280 = self.__bmp280.getTemp()
        # print("bmp280:temp={},Presure={},Altitude={}".format(temp,pres,alt))

    def hdc1080TimerHandler(self, timer):
        self.__sensorData.temp = self.__hdc1080.temperature
        self.__sensorData.humi = self.__hdc1080.humidity
        self.__sensorData.wetBulbTemp = self.aac.ts(self.__sensorData.temp, self.__sensorData.humi/100.0, 0.1)
        #print("hdc1080:temp={},humi={},wetBulbTemp={}".format(self.__sensorData.temp, self.__sensorData.humi,self.__sensorData.wetBulbTemp))

    def timerHandler(self, timer):
        #print("read sensor data...")
        self.bmp280TimerHandler(timer)
        self.hdc1080TimerHandler(timer)

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
            base = (self.config["pwm1min"]/100)*self.config["pwm1freq"]
            full = (self.config["pwm1max"] - self.config["pwm1min"])/100*self.config["pwm1freq"]
            duty = 1023*(full * (percent / 100.0) + base) /self.config["pwm1freq"]
            print("base:{},full:{},duty:{}".format(base,full,int(duty)))
            if duty > self.config["pwm1freq"]:
                duty = self.config["pwm1freq"]
        #第1组用于直接控制mos，给风扇供应电源
        if duty == 0:
            self.__fan1PwmPin.duty(0)
            print("PWM duty1:{}，duty2:{}".format(0,int(duty)))
        else:
            self.__fan1PwmPin.duty(1023)
            print("PWM duty1:{}，duty2:{}".format(1023,int(duty)))
			
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

        # print("setWaterPump duty:{}".format(int(duty)))
        self.__pwmWaterBump.duty(int(duty))

    def getWaterTankStatus(self):
        if self.__waterTankTopSensor.value() == 1:
            return enum.WaterMark.FULL
        elif self.__waterTankTopSensor.value() == 0 and self.__waterTankBottomSensor.value() == 0:
            return enum.WaterMark.NORMAL
        elif self.__waterTankTopSensor.value() == 0 and self.__waterTankBottomSensor.value() == 1:
            return enum.WaterMark.EMPTY
        else:
            print("[ERROR]:default water full status.")
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
    
    @classmethod
    def getInstance(cls):
        """获取单例实例"""
        if cls.__instance is None:
            cls.__instance = BSP()
        return cls.__instance
