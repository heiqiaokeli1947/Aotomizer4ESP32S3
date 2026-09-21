# 操作esp32引脚
#from machine import Pin

# 操作时间 延迟几秒等
from domain.LogUtils import log
import time
# 网络相关的函数
import network
import sys

# esp32 引脚2是一颗自带的 led的灯
#light = Pin(2, Pin.OUT)

def connectToWifi(ssid, pwd):
    # wifi模式
    wlan = network.WLAN(network.STA_IF)
    # 激活
    wlan.active(True)
    log("init wifi...")
    try:
        #  连接超时设置
        start_time = time.time()
        log("start time:{}".format(start_time))
        if not wlan.isconnected():
            log("try to connect ssid:{} pwd:{}".format(ssid, pwd))
            wlan.connect(ssid, pwd)
            while not wlan.isconnected():
                log("connect failed,sleep 1s")
                time.sleep(1)
                # 15秒内没连接上就是超时了
                log("now time:{}".format(time.time()))
                us = time.time() - start_time
                log("use time:{}".format(us))
                if us > 35:
                    log("connect wifi timeout.")
                    #wlan.active(False)
                    return False
            log("connect success.")
            #light.value(1)
            # 打印 网络信息
            log("ifconfig:", wlan.ifconfig())
            return True
        else:
            log("connect success.")
            #light.value(1)
            # 打印 网络信息
            log("ifconfig:", wlan.ifconfig())
            return True
    except Exception as e:
        sys.print_exception(e)
        log('connect exception.')
        #wlan.active(False)
        return False
    finally:
        log('connectWiFi finish')


def getStationIP():
    wlan = network.WLAN(network.STA_IF)
    if wlan.active() and wlan.isconnected():
        return wlan.ifconfig()[0]
    else:
        return "Station not active or not connected."


def testWifiConnect(ssid, pwd):
    log("try to connect ssid:{} pwd:{}".format(ssid, pwd))
    # wifi模式
    wlan = network.WLAN(network.STA_IF)
    # 激活
    log("init wifi...")
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)

    try:
        #  连接超时设置
        start_time = time.time()
        log("start time:{}".format(start_time))
        wlan.connect(ssid, pwd)
        while not wlan.isconnected():
            log("sleep 1s then retry.")
            time.sleep(1)
            # 15秒内没连接上就是超时了
            #log("now time:{}".format(time.time()))
            us = time.time() - start_time
            #log("use time:{}".format(us))
            if us > 35:
                log("test connect failed by timeout.")
                return False
        # 打印 网络信息
        log("test connect success! ifconfig:", wlan.ifconfig())
        return True
    except Exception as e:
        sys.print_exception(e)
        log('test connect exception.')
        #wlan.active(False)
        return False
    finally:
        log('test connect WiFi finish.')


def startAP(apname, appwd, forConfig=False):
    try:
        # 创建Wi-Fi接入点
        ap = network.WLAN(network.AP_IF)
        # 启用接入点
        #ap.active(False)
        #time.sleep(1)
        ap.active(True)
        if forConfig:
            tmpName = apname + "_" + ap.ifconfig()[0]
        else:
            tmpName = apname
        log("start ap:{},{}".format(tmpName, appwd))
        # 设置接入点参数
        ap.config(essid=tmpName, authmode=network.AUTH_WPA_WPA2_PSK, password=appwd)
        # 输出接入点IP地址
        log('AP IP address:{}'.format(tmpName))
        return True
    except Exception as e:
        sys.print_exception(e)
        log('start AP exception.')
        #ap.active(False)
        return False
    finally:
        log('start AP finish.')


def startBroadcastAP(apname, appwd):
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=apname, authmode=network.AUTH_WPA_WPA2_PSK, password=appwd)
        return True
    except Exception as e:
        sys.print_exception(e)
        log('start AP exception.')
        return False
    finally:
        log('start AP finish.')


def getAPIP():
    ap = network.WLAN(network.AP_IF)
    if ap.active():
        return ap.ifconfig()[0]
    else:
        return "AP not active."


def stopAP():
    try:
        log('stop AP...')
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
        return True
    except Exception as e:
        sys.print_exception(e)
        log('stop AP exception.')
        #ap.active(False)
        return False
    finally:
        log('stop AP finish.')


def isConnected():
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected()


def scanAP():
    try:
        log('scan AP...')
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        res = wlan.scan()  #(ssid, bssid, channel, RSSI, security, hidden)
        result = {}
        for item in res:
            if len(item[0]) != 0:
                result[item[0]] = item[3]
        log('Find AP:{}'.format(result))
        return result
    except Exception as e:
        sys.print_exception(e)
        log('scan AP exception.')
        return {}
    finally:
        log('scan AP finish.')