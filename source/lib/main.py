# SPDX-FileCopyrightText: 2024 Wai Weng for Cytron Technologies
#
# SPDX-License-Identifier: MIT

"""
DESCRIPTION:
Main program for the MODBUS RTU IO Expander.

AUTHOR  : Wai Weng
COMPANY : Cytron Technologies Sdn Bhd
WEBSITE : www.cytron.io
EMAIL   : support@cytron.io
"""

import board
import time
from microcontroller import watchdog
from watchdog import WatchDogMode
import iriv_ioc_modbus
import iriv_ioc_hal as Hal
import web_status
import os
import rs485_sensor


# Setup watchdog timer.
try:
    # Use longer timeout in TCP mode because network stack may block.
    if getattr(iriv_ioc_modbus, "modbus_mode", None) == "TCP":
        watchdog.timeout = 120
    else:
        watchdog.timeout = 5
except Exception:
    watchdog.timeout = 5
watchdog.mode = WatchDogMode.RESET

timestamp = time.monotonic()

while True:
    try:
        # Feed early to avoid resets if processing blocks.
        watchdog.feed()
        result = iriv_ioc_modbus.client.process()
    except KeyboardInterrupt:
        print('KeyboardInterrupt, stopping RTU client...')
        break
    except Exception as e:
        print('Exception during execution: {}'.format(e))
    
    # Handle web status server (non-blocking).
    try:
        web_status.process()
    except Exception as e:
        # Keep running even if web server fails.
        pass
    
    # Poll RS485 temperature sensor (non-blocking schedule).
    try:
        rs485_sensor.process()
    except Exception:
        pass
    
    # Blink LED.
    if (time.monotonic() - timestamp >= 0.5):
        timestamp = time.monotonic()
        Hal.led.value ^= 1
        
    # Feeding Watchdog Timer.
    watchdog.feed()