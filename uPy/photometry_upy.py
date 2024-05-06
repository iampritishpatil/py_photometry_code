# Code that runs on the pyboard which handles data acquisition and streaming data to
# the host computer.
# Copyright (c) Thomas Akam 2018-2023.  Licenced under the GNU General Public License v3.

import micropython
import pyb
import gc
from array import array

from ucollections import namedtuple


micropython.alloc_emergency_exception_buf(200)  # Allocate space for error messages raised during interrupt processing.

import hardware_config as hwc


#pritish
from ucollections import namedtuple

PulseSettings =  namedtuple("PulseSettings", (
    "adc1",
    "adc2",
    "LED1",
    "LED2",
    "LED3"
    )
)

protocols_pulsed = {
    "2EX_1EM_pulsed": [
        PulseSettings(adc1=True, adc2=False, LED1=True, LED2=False, LED3=False),
        PulseSettings(adc1=True, adc2=False, LED1=False, LED2=True, LED3=False)
    ],
    "2EX_2EM_pulsed": [
        PulseSettings(adc1=True, adc2=False, LED1=True, LED2=False, LED3=False),
        PulseSettings(adc1=False, adc2=True, LED1=False, LED2=True, LED3=False)
    ],
    "3EX_2EM_pulsed": [
        PulseSettings(adc1=True, adc2=False, LED1=True, LED2=False, LED3=False),
        PulseSettings(adc1=False, adc2=True, LED1=False, LED2=True, LED3=False),
        PulseSettings(adc1=True, adc2=False, LED1=False, LED2=False, LED3=True)
    ],
    
    "cyRFP_pulsed" : [
        PulseSettings(adc1=True, adc2=True, LED1=True, LED2=False, LED3=False),
    ],

    "cyRFP_iso_pulsed" : [
        PulseSettings(adc1=True, adc2=True, LED1=True, LED2=False, LED3=False),
        PulseSettings(adc1=True, adc2=False, LED1=False, LED2=True, LED3=False),
    ]
}

write_ind2pulse = {
    "2EX_1EM_pulsed": [0, 1],
    "2EX_2EM_pulsed": [0, 1],
    "3EX_2EM_pulsed": [0, 1, 2],
    "cyRFP_pulsed": [0,0],
    "cyRFP_iso_pulsed": [0,0,1]
}




# Photometry class.


class Photometry:
    def __init__(self):
        self.ADC1 = pyb.ADC(hwc.pins["analog_1"])
        self.ADC2 = pyb.ADC(hwc.pins["analog_2"])
        
        # self.adcs = (self.ADC1, self.ADC2)

        self.DI1 = pyb.Pin(hwc.pins["digital_1"], pyb.Pin.IN, pyb.Pin.PULL_DOWN)
        self.DI2 = None
        self.LED1 = pyb.DAC(1, bits=12)
        self.LED2 = pyb.DAC(2, bits=12)
        self.LED3 = None
        self.ovs_buffer = array("H", [0] * 64)  # Oversampling buffer
        
        self.ovs_timer = pyb.Timer(2)  # Oversampling timer.
        self.sampling_timer = pyb.Timer(3)
        self.usb_serial = pyb.USB_VCP()
        self.running = False
        self.unique_id = int.from_bytes(pyb.unique_id(), "little")

        #pritish
        self.ovs_buffer_adc1 = array("H", [0] * 64)  # Oversampling buffer
        self.ovs_buffer_adc2 = array("H", [0] * 64)  # Oversampling buffer

        # self.ovs_buffers = (self.ovs_buffer_adc1, self.ovs_buffer_adc2)

    def set_mode(self, mode):
        # Set the acquisition mode.
        assert mode in ["2EX_2EM_continuous", "2EX_1EM_pulsed", "2EX_2EM_pulsed", "3EX_2EM_pulsed",
                        "cyRFP_pulsed", "cyRFP_iso_pulsed"
                        ], "Invalid mode."
        self.mode = mode
        
        #defaults
        self.n_digital_signals = 2 #generally 2 digital signals are used
        self.DI2 = pyb.Pin(hwc.pins["digital_2"], pyb.Pin.IN, pyb.Pin.PULL_DOWN) 
        self.LED3 = None
        # self.n_analog_signals = 2
        self.oversampling_rate = hwc.oversampling_rate["pulsed"]
        self.n_analog_signals = hwc.n_signals[mode]
        

        #overwirite defaults for specific modes
        if mode == "2EX_2EM_continuous":
            self.oversampling_rate = hwc.oversampling_rate["continuous"]
        elif mode == "3EX_2EM_pulsed":
            # self.n_analog_signals = 3
            #this one overwrites the digital input to be output.
            self.n_digital_signals = 1 # Only one digital signal for 3EX_2EM.
            self.DI2 = None
            self.LED3 = pyb.Pin(hwc.pins["digital_2"], pyb.Pin.OUT, pyb.Pin.PULL_DOWN)
        # elif mode == "cyRFP_iso_pulsed":           
            # self.n_analog_signals = 3
        #add configs for the modes
        if mode in protocols_pulsed:
            self.n_pulses = hwc.n_pulses[mode]
            self.pulse_config = protocols_pulsed[mode]
            self.write_ind2pulse = write_ind2pulse[mode]

    def set_LED_current(self, LED_1_current=None, LED_2_current=None):
        # Set the LED current.
        if LED_1_current is not None:
            if LED_1_current == 0:
                self.LED_1_value = 0
            else:
                self.LED_1_value = int(hwc.LED_calibration["slope"] * LED_1_current + hwc.LED_calibration["offset"])
            if self.running and (self.mode == "2EX_2EM_continuous"):
                self.LED1.write(self.LED_1_value)
        if LED_2_current is not None:
            if LED_2_current == 0:
                self.LED_2_value = 0
            else:
                self.LED_2_value = int(hwc.LED_calibration["slope"] * LED_2_current + hwc.LED_calibration["offset"])
            if self.running and (self.mode == "2EX_2EM_continuous"):
                self.LED2.write(self.LED_2_value)

    def start(self, sampling_rate, buffer_size):
        # Start acquisition, stream data to computer, wait for ctrl+c over serial to stop.
        # Setup sample buffers.
        self.buffer_size = buffer_size
        self.sample_buffers = (array("H", [0] * buffer_size), array("H", [0] * buffer_size))
        self.buffer_data_mv = (memoryview(self.sample_buffers[0]), memoryview(self.sample_buffers[1]))
        self.chunk_header = array("H", [0, 0])
        self.sample = 0
        self.baseline = 0
        self.dig_sample = False

        #pritish
        self.sample_adc1 = 0
        self.sample_adc2 = 0
        self.baseline_adc1 = 0
        self.baseline_adc2 = 0

        #end pritish

        self.write_buf = 0  # Buffer to write data to.
        self.send_buf = 1  # Buffer to send data from.
        self.write_ind = 0  # Buffer index to write new data to.
        self.buffer_ready = False  # Set to True when full buffer is ready to send.
        self.chunk_number = 0  # Number of data chunks sent to computer, modulo 2**16.
        self.running = True
        self.ovs_timer.init(freq=self.oversampling_rate)
        self.usb_serial.setinterrupt(-1)  # Disable serial interrupt.
        gc.collect()
        gc.disable()
        if self.mode == "2EX_2EM_continuous":
            self.sampling_timer.init(freq=sampling_rate)
            self.sampling_timer.callback(self.continuous_ISR)
            self.LED1.write(self.LED_1_value)
            self.LED2.write(self.LED_2_value)
        else:
            self.sampling_timer.init(freq=sampling_rate * self.n_pulses)
            self.sampling_timer.callback(self.pulsed_ISR_v2)
        while True:
            if self.buffer_ready:
                self._send_buffer()
            if self.usb_serial.any():
                self.recieved_byte = self.usb_serial.read(1)
                if self.recieved_byte == b"\xFF":  # Stop signal.
                    break
                elif self.recieved_byte == b"\xFD":  # Set LED 1 power.
                    self.set_LED_current(LED_1_current=int.from_bytes(self.usb_serial.read(2), "little"))
                elif self.recieved_byte == b"\xFE":  # Set LED 2 power.
                    self.set_LED_current(LED_2_current=int.from_bytes(self.usb_serial.read(2), "little"))
        self.stop()

    def stop(self):
        # Stop aquisition
        self.sampling_timer.deinit()
        self.ovs_timer.deinit()
        self.LED1.write(0)
        self.LED2.write(0)
        self.running = False
        self.usb_serial.setinterrupt(3)  # Enable serial interrupt.
        gc.enable()

    @micropython.native
    def continuous_ISR(self, t):
        # Interrupt service routine for 2 color continous acquisition mode.
        # self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)  # Read sample of analog 1.
        # self.sample = sum(self.ovs_buffer) >> 3
        # self.sample_buffers[self.write_buf][self.write_ind] = (self.sample << 1) | self.DI1.value()
        # self.write_ind += 1
        # self.ADC2.read_timed(self.ovs_buffer, self.ovs_timer)  # Read sample of analog 2.
        # self.sample = sum(self.ovs_buffer) >> 3
        # self.sample_buffers[self.write_buf][self.write_ind] = (self.sample << 1) | self.DI2.value()
        # # Update write index and switch buffers if full.
        # self.write_ind = (self.write_ind + 1) % self.buffer_size
        # if self.write_ind == 0:  # Buffer full, switch buffers.
        #     self.write_buf = 1 - self.write_buf
        #     self.send_buf = 1 - self.send_buf
        #     self.buffer_ready = True
        
        
        #pritish
        # pyb.ADC.read_timed_multi((self.ADC1, self.ADC2), (self.ovs_buffer_adc1, self.ovs_buffer_adc2), self.ovs_timer)
        # pyb.ADC.read_timed_multi(self.adcs, self.ovs_buffers, self.ovs_timer)

        self.ADC1.read_timed(self.ovs_buffer_adc1, self.ovs_timer)
        pyb.udelay(1)  # Wait before reading ADC (us).
        self.ADC2.read_timed(self.ovs_buffer_adc2, self.ovs_timer)
        pyb.udelay(1)  # Wait before reading ADC (us).

        
        self.sample = sum(self.ovs_buffer_adc1) >> 3
        self.sample_buffers[self.write_buf][self.write_ind] = (self.sample << 1) | self.DI1.value()
        self.write_ind = (self.write_ind + 1) % self.buffer_size

        self.sample = sum(self.ovs_buffer_adc2) >> 3
        self.sample_buffers[self.write_buf][self.write_ind] = (self.sample << 1) | self.DI2.value()
        self.write_ind = (self.write_ind + 1) % self.buffer_size


        if self.write_ind == 0:  # Buffer full, switch buffers.
            self.write_buf = 1 - self.write_buf
            self.send_buf = 1 - self.send_buf
            self.buffer_ready = True


    @micropython.native
    def pulsed_ISR(self, t):
        # Interrupt service routine for pulsed acquisition modes.

        # Read baseline, turn on LED.
        write_ind_mod = self.write_ind % self.n_analog_signals

        if write_ind_mod == 0:  # Photoreciever=1, LED=1.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED1.write(self.LED_1_value)
        elif write_ind_mod == 1 and self.mode == "2EX_1EM_pulsed":  # Photoreciever=1, LED=2.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED2.write(self.LED_2_value)
        elif write_ind_mod == 1:  # Photoreciever=2, LED=2.
            self.ADC2.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED2.write(self.LED_2_value)
        elif write_ind_mod == 2:  # Photoreciever=1, LED=3.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED3.value(1)
        
        self.baseline = sum(self.ovs_buffer) >> 3

        pyb.udelay(300)  # Wait before reading ADC (us).

        # Read sample, turn off LED.
        if write_ind_mod == 0:  # Photoreciever=1, LED=1.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.dig_sample = self.DI1.value()
            self.LED1.write(0)
        elif write_ind_mod == 1 and self.mode == "2EX_1EM_pulsed":  # Photoreciever=1, LED=2.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED2.write(0)
        elif write_ind_mod == 1:  # Photoreciever=2, LED=2.
            self.ADC2.read_timed(self.ovs_buffer, self.ovs_timer)
            self.dig_sample = False if self.mode == "3EX_2EM_pulsed" else self.DI2.value()
            self.LED2.write(0)
        elif write_ind_mod == 2:  # Photoreciever=1, LED=3.
            self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
            self.LED3.value(0)
            self.dig_sample = False
        self.sample = sum(self.ovs_buffer) >> 3

        # Subtract baseline and  store sample in buffer.
        self.sample = max(self.sample - self.baseline, 0)
        self.sample_buffers[self.write_buf][self.write_ind] = (self.sample << 1) | self.dig_sample

        # Update write index and switch buffers if buffer full.
        self.write_ind = (self.write_ind + 1) % self.buffer_size
        if self.write_ind == 0:  # Buffer full, switch buffers.
            self.write_buf = 1 - self.write_buf
            self.send_buf = 1 - self.send_buf
            self.buffer_ready = True


        #pritish
    @micropython.native
    def pulsed_ISR_v2(self, t):
        # Interrupt service routine for pulsed acquisition modes.

        write_ind_mod = self.write_ind % self.n_analog_signals
        pulse = self.write_ind2pulse[write_ind_mod]
        # Read baseline, turn on LED.
        pc = self.pulse_config[pulse]

        # if pc.adc1 and pc.adc2:
        # pyb.ADC.read_timed_multi(self.adcs, self.ovs_buffers, self.ovs_timer)
        if pc.adc1:
            self.ADC1.read_timed(self.ovs_buffer_adc1, self.ovs_timer)
            pyb.udelay(1)  # Wait before reading ADC (us).
        if pc.adc2:
            self.ADC2.read_timed(self.ovs_buffer_adc2, self.ovs_timer)
            pyb.udelay(1)  # Wait before reading ADC (us).
        

        if pc.LED1:
            self.LED1.write(self.LED_1_value)
        if pc.LED2:
            self.LED2.write(self.LED_2_value)
        if pc.LED3:
            self.LED3.value(1)

        self.baseline_adc1 = sum(self.ovs_buffer_adc1) >> 3
        self.baseline_adc2 = sum(self.ovs_buffer_adc2) >> 3


        pyb.udelay(300)  # Wait before reading ADC (us).

        # if pc.adc1 and pc.adc2:
        # pyb.ADC.read_timed_multi(self.adcs, self.ovs_buffers, self.ovs_timer)
        if pc.adc1:
            self.ADC1.read_timed(self.ovs_buffer_adc1, self.ovs_timer)
            pyb.udelay(1)  # Wait before reading ADC (us).
        if pc.adc2:
            self.ADC2.read_timed(self.ovs_buffer_adc2, self.ovs_timer)
            pyb.udelay(1)  # Wait before reading ADC (us).

        if pc.LED1:
            self.LED1.write(0)
        if pc.LED2:
            self.LED2.write(0)
        if pc.LED3:
            self.LED3.value(0)

        self.sample_adc1 = sum(self.ovs_buffer_adc1) >> 3
        self.sample_adc2 = sum(self.ovs_buffer_adc2) >> 3

        self.sample_adc1 = max(self.sample_adc1 - self.baseline_adc1, 0)
        self.sample_adc2 = max(self.sample_adc2 - self.baseline_adc2, 0)

        
        if write_ind_mod == 0:        
            digital = self.DI1.value()
        elif write_ind_mod == 1 and self.n_digital_signals == 2:
            digital = self.DI2.value()
        else:
            digital = 0
        
        # digital2 = self.DI2.value() if self.DI2 else 0

        if pc.adc1 and pc.adc2:
            #write frist sample
            self.sample_buffers[self.write_buf][self.write_ind] = (self.sample_adc1 << 1) | digital
            self.write_ind = (self.write_ind + 1) % self.buffer_size

            write_ind_mod = self.write_ind % self.n_analog_signals
            if write_ind_mod == 0:        
                digital = self.DI1.value()
            elif write_ind_mod == 1 and self.n_digital_signals == 2:
                digital = self.DI2.value()
            else:
                digital = 0
            #write second sample
            self.sample_buffers[self.write_buf][self.write_ind] = (self.sample_adc2 << 1) | digital

        elif pc.adc1:
            self.sample_buffers[self.write_buf][self.write_ind] = (self.sample_adc1 << 1) | digital
        elif pc.adc2:
            self.sample_buffers[self.write_buf][self.write_ind] = (self.sample_adc2 << 1) | digital

        # Update write index and switch buffers if buffer full.
        self.write_ind = (self.write_ind + 1) % self.buffer_size

        if self.write_ind == 0:  # Buffer full, switch buffers.
            self.write_buf = 1 - self.write_buf
            self.send_buf = 1 - self.send_buf
            self.buffer_ready = True

        

    @micropython.native
    def _send_buffer(self):
        # Send full buffer to host computer. Each chunk of data sent to computer is
        # preceded by a 5 byte header containing the byte b'\x07' indicating the
        # start of a chunk, then the chunk_number and checksum encoded as 2 byte integers.
        self.chunk_number = (self.chunk_number + 1) & 0xFFFF
        self.chunk_header[0] = self.chunk_number
        self.chunk_header[1] = sum(self.buffer_data_mv[self.send_buf]) & 0xFFFF  # Checksum
        self.usb_serial.write(b"\x07")
        self.usb_serial.write(self.chunk_header)
        self.usb_serial.send(self.sample_buffers[self.send_buf])
        self.buffer_ready = False
