# Hardware config.

pins = {
    "analog_1": "X11",
    "analog_2": "X12",
    "digital_1": "Y7",
    "digital_2": "Y8",
}  # Pyboard Pins used for analog and digital signals.

LED_calibration = {
    "slope": 9.78,
    "offset": 6.26,
}  # Calibration of DAC values against LED currents: DAC_value = offset + slope * LED_current_mA.

ADC_volts_per_division = [0.00010122, 0.00010122]  # Analog signal volts per division for signal [1, 2]

max_sampling_rate = {  # Maximum sampling rate in continuous and time division acquisition modes (Hz).
    "continuous": 1000,
    "pulsed": 260,  # For pulsed modes the max sampling rate is per analog channel.
}

max_LED_current = {  # Maximum LED current in continuous and time division acquisition modes (mA).
    "continuous": 100, # supposed to not be increased for the continuous mode to avoid overheating the LED.
    "pulsed": 200,
}

oversampling_rate = {"continuous": 3e5, "pulsed": 256e3}  # Rate at which ADC samples are aquired for oversampling.
