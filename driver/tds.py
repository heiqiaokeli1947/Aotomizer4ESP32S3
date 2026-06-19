from machine import UART
import time


class TDSModule:
    FRAME_HEAD = 0x55
    SEND_FRAME_LEN = 0x07
    RECIVE_FRAME_LEN = 0x0B
    CMD_READ_DATA = 0x05
    CMD_SLEEP = 0x06

    def __init__(self, tx_pin, rx_pin, uart_id=1, baudrate=9600):
        self.uart = UART(uart_id, baudrate=baudrate, tx=tx_pin, rx=rx_pin, timeout=500)
        self.rx_buf = bytearray()

    def calc_checksum(self, data):
        cs = 0
        for b in data:
            cs += b
        return cs & 0xFF

    def send_cmd(self, channel):
        if channel not in (1, 2):
            raise ValueError("通道仅支持1或2")
        ch_byte = 0x01 if channel == 1 else 0x02
        frame = bytearray([
            self.FRAME_HEAD,
            self.SEND_FRAME_LEN,
            self.CMD_READ_DATA,
            ch_byte,
            0x00, 0x00, 0x00
        ])
        cs = self.calc_checksum(frame)
        frame.append(cs)
        #print("发送数据:", frame.hex())
        self.uart.write(frame)

    def read_response(self, timeout_ms=100):
        self.rx_buf = bytearray()
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                self.rx_buf.extend(self.uart.read())
                if len(self.rx_buf) >= self.RECIVE_FRAME_LEN:
                    #print("接收到的数据:", self.rx_buf.hex())
                    idx = self.rx_buf.find(bytes([self.FRAME_HEAD]))
                    if idx != -1 and idx + self.RECIVE_FRAME_LEN <= len(self.rx_buf):
                        frame = self.rx_buf[idx:idx+self.RECIVE_FRAME_LEN]
                        #print("接收到的frame:", frame.hex())
                        recv_cs = frame[-1]
                        calc_cs = self.calc_checksum(frame[:-1])
                        if recv_cs == calc_cs:
                            #print("校验和校验通过，返回数据:", frame.hex())
                            return frame
                        else:
                            self.rx_buf = self.rx_buf[idx+self.RECIVE_FRAME_LEN:]
        return None

    def get_channel_data(self, channel):
        self.send_cmd(channel)
        time.sleep_ms(30)
        frame = self.read_response()
        if frame is None:
            return None
        resp_cmd = frame[2]
        if resp_cmd != 0x85:
            return None
        recv_ch = frame[3]
        target_ch = 0x01 if channel == 1 else 0x02
        if recv_ch != target_ch:
            return None
        # 电导率: 高字节在前，低字节在后，单位 0.1 μS/cm
        cond_raw = (frame[4] << 8) | frame[5]
        cond = cond_raw / 10.0
        # 温度: 高字节在前，低字节在后，单位 0.1 ℃，有符号数
        temp_raw = (frame[6] << 8) | frame[7]
        # 处理有符号温度值
        if temp_raw > 32767:
            temp_raw = temp_raw - 65536
        temp = temp_raw / 10.0
        # TDS 计算: 电导率 / 2
        tds = cond / 2.0
        return {
            "conductivity_uscm": cond,
            "temp_c": temp,
            "tds_ppm": tds
        }

    def get_both_channels(self):
        ch1 = self.get_channel_data(1)
        time.sleep_ms(10)
        ch2 = self.get_channel_data(2)
        return {"ch1": ch1, "ch2": ch2}

    def get_channel(self,channel):
        return self.get_channel_data(channel)

    def sleep_module(self):
        frame = bytearray([self.FRAME_HEAD, self.SEND_FRAME_LEN, self.CMD_SLEEP, 0x00, 0x00, 0x00, 0x00])
        cs = self.calc_checksum(frame)
        frame.append(cs)
        self.uart.write(frame)
        print("模块已进入休眠")
