
import utime

class LogUtils:
    def __init__(self,obj):
        if type(obj) is str:
            self.__LoggerName = obj
        else:
            self.__LoggerName = obj.__class__.__name__

    def getLocalTimeStamp(self):
        year, month, mday, hour, minute, second, weekday, yearday = utime.localtime()
        return str(year)+"-"+str(month)+"-"+str(mday)+" "+str(hour)+":"+str(minute)+":"+str(second)
    
    def info(self,log):
        print("[{}] [{}] Info:{}".format(self.getLocalTimeStamp(),self.__LoggerName, log))

    def warn(self,log):
        print("[{}] [{}] Warn:{}".format(self.getLocalTimeStamp(),self.__LoggerName, log))

    def error(self,log):
        print("[{}] [{}] Error:{}".format(self.getLocalTimeStamp(),self.__LoggerName, log))
