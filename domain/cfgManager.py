import uio,ujson

configFilePath='/resource/system.config'
DEFAULT_CONFIG={"deviceusername": "admin", "devicepwd": "pengping", "wifipwdDefault": "13438045703", "devicetype": "NodeMCU", "num2name": "Tree humidity", "APName": "SmartNode", "sw2name": "S2", "id": 1, "wifiname": "cissco_2g", "ver": "1.1", "serverurl": "192.168.1.124", "APNetMask": "255.255.255.0", "altitude": 498.0, "wifinameDefault": "IOT_2G", "latitude": 30.67831, "serverurlDefault": "http://3a892544f7.qicp.vip", "APPwd": "19880612", "devicename": "Smart Node", "num1name": "Tree temprature", "rangename": "Tree light", "mode": "config", "sw1name": "S1", "wifipwd": "1343804570", "APGateway": "192.168.1.1", "APIP": "123", "longitude": 104.0375}

def createDefaultConfig():
    try:
        with uio.open(configFilePath,"w") as f:
            conf=ujson.dumps(DEFAULT_CONFIG)
            f.write(conf)
    except OSError:
        print("create default config file error.")


def loadCfg():
    try:
        with uio.open(configFilePath,"r") as f:
            conf = ujson.loads(f.read())
            print("conf in file:{}".format(conf))
            return conf
    except OSError:
        print("read cfg failed,I will create default config.")
        createDefaultConfig()
        return DEFAULT_CONFIG
        
def saveCfg(newCfg):
    try:
        with uio.open(configFilePath,"w") as f:
            conf=ujson.dumps(newCfg)
            print("new conf:{}".format(conf))
            f.write(conf)
    except OSError:
        print("save cfg failed.")