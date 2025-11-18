# SPDX-License-Identifier: MIT
"""
RS485 temperature sensor poller (Modbus RTU master) for IRIV-IOC.
Active only when MODBUS_MODE == "TCP" and RS485_SENSOR_ENABLE is true.
Reads one register from a configured slave and exposes the latest value.
"""

import os
import time
import board

from umodbus.serial import Serial


_enabled = False
_serial = None
_slave_addr = 1
_reg_addr = 0
_use_input_regs = True
_signed = False
_scale = 0.1
_format = "int16"  # int16|uint16|float32|float32_swapped
_qty = 1

# Optional humidity channel
_hum_enable = False
_hum_reg = 1
_hum_signed = False
_hum_scale = 0.1
_hum_format = "int16"
_hum_qty = 1
_poll_s = 2.0

_last_value = None
_last_raw = None
_last_ok = False
_last_ts = 0.0
_next_poll = 0.0
_err_count = 0

_last_hum = None
_last_hum_raw = None
_last_hum_ok = False


def _parse_bool(v, default=False):
    try:
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    except Exception:
        pass
    return default


def _init():
    global _enabled, _serial, _slave_addr, _reg_addr, _use_input_regs, _signed, _scale, _poll_s, _next_poll
    global _format, _qty, _hum_enable, _hum_reg, _hum_signed, _hum_scale, _hum_format, _hum_qty
    try:
        if os.getenv("MODBUS_MODE") != "TCP":
            _enabled = False
            return
        if not _parse_bool(os.getenv("RS485_SENSOR_ENABLE"), False):
            _enabled = False
            return
        # Configured/enabled at this point
        _enabled = True
        # Profile presets (SN_HUTE sets typical defaults)
        profile = (os.getenv("RS485_SENSOR_PROFILE") or "GENERIC").strip().upper()
        # Defaults
        d_func = "IREG"
        d_reg = 0
        d_scale = 0.1
        d_fmt = "int16"
        d_qty = 1
        d_h_en = False
        d_h_reg = 1
        d_h_scale = 0.1
        d_h_fmt = "int16"
        d_h_qty = 1
        if profile == "SN_HUTE":
            # Typical: Holding registers 0x0001 temp (0.1 C), 0x0002 RH (0.1 %)
            d_func = "HREG"
            d_reg = 1
            d_scale = 0.1
            d_fmt = "int16"
            d_qty = 1
            d_h_en = True
            d_h_reg = 2
            d_h_scale = 0.1
            d_h_fmt = "int16"
            d_h_qty = 1
        _slave_addr = int(os.getenv("RS485_SENSOR_ADDR") or 1)
        _reg_addr = int(os.getenv("RS485_SENSOR_REG") or d_reg)
        func = (os.getenv("RS485_SENSOR_FUNC") or d_func).strip().upper()
        _use_input_regs = (func != "HREG")
        _signed = _parse_bool(os.getenv("RS485_SENSOR_SIGNED"), False)
        _format = (os.getenv("RS485_SENSOR_FORMAT") or d_fmt).strip().lower()
        try:
            _qty = int(os.getenv("RS485_SENSOR_QTY") or (2 if _format.startswith("float32") else d_qty))
        except Exception:
            _qty = 1
        try:
            _scale = float(os.getenv("RS485_SENSOR_SCALE") or d_scale)
        except Exception:
            _scale = 0.1
        # Humidity channel
        _hum_enable = _parse_bool(os.getenv("RS485_SENSOR_HUM_ENABLE"), d_h_en)
        if _hum_enable:
            _hum_reg = int(os.getenv("RS485_SENSOR_HUM_REG") or d_h_reg)
            _hum_signed = _parse_bool(os.getenv("RS485_SENSOR_HUM_SIGNED"), False)
            _hum_format = (os.getenv("RS485_SENSOR_HUM_FORMAT") or d_h_fmt).strip().lower()
            try:
                _hum_qty = int(os.getenv("RS485_SENSOR_HUM_QTY") or (2 if _hum_format.startswith("float32") else d_h_qty))
            except Exception:
                _hum_qty = 1
            try:
                _hum_scale = float(os.getenv("RS485_SENSOR_HUM_SCALE") or d_h_scale)
            except Exception:
                _hum_scale = 0.1
        try:
            _poll_s = float(os.getenv("RS485_SENSOR_POLL_SEC") or 2)
            if _poll_s < 0.2:
                _poll_s = 0.2
        except Exception:
            _poll_s = 2.0
        baud = int(os.getenv("RS485_SENSOR_BAUD") or os.getenv("MODBUS_RTU_BAUDRATE") or 9600)
        # Create a serial RTU interface as Modbus master transport
        _serial = Serial(tx_pin=board.TX, rx_pin=board.RX, baudrate=baud)
        _next_poll = time.monotonic()
    except Exception:
        # Stay logically enabled so the dashboard shows Enabled: YES,
        # but mark serial unavailable; process() will keep trying.
        _serial = None


def _decode_vals(vals, fmt, signed, scale):
    # vals is a tuple of 16-bit integers
    if fmt == "int16":
        raw = int(vals[0])
        return raw, raw * scale
    if fmt == "uint16":
        raw = int(vals[0]) & 0xFFFF
        return raw, raw * scale
    if fmt == "float32":
        # big-endian registers [MSW, LSW]
        msw = int(vals[0]) & 0xFFFF
        lsw = int(vals[1]) & 0xFFFF
        bin32 = (msw << 16) | lsw
        # IEEE754 decode
        import struct
        f = struct.unpack('!f', struct.pack('!I', bin32))[0]
        return bin32, f * scale
    if fmt == "float32_swapped":
        # little-endian word order [LSW, MSW]
        lsw = int(vals[0]) & 0xFFFF
        msw = int(vals[1]) & 0xFFFF
        bin32 = (msw << 16) | lsw
        import struct
        f = struct.unpack('!f', struct.pack('!I', bin32))[0]
        return bin32, f * scale
    # default fallback
    raw = int(vals[0])
    return raw, raw * scale


def process():
    global _next_poll, _last_value, _last_raw, _last_ok, _last_ts, _err_count
    global _last_hum, _last_hum_raw, _last_hum_ok
    if not _enabled:
        if _serial is None:
            _init()
        return
    now = time.monotonic()
    if now < _next_poll:
        return
    _next_poll = now + _poll_s
    try:
        if _use_input_regs:
            vals = _serial.read_input_registers(slave_addr=_slave_addr, starting_addr=_reg_addr, register_qty=_qty, signed=_signed)
        else:
            vals = _serial.read_holding_registers(slave_addr=_slave_addr, starting_addr=_reg_addr, register_qty=_qty, signed=_signed)
        raw, val = _decode_vals(vals, _format, _signed, _scale)
        _last_raw = raw
        _last_value = val
        _last_ok = True
        _last_ts = now
    except Exception:
        _err_count += 1
        _last_ok = False
    # Humidity (optional)
    if _hum_enable:
        try:
            if _use_input_regs:
                hvals = _serial.read_input_registers(slave_addr=_slave_addr, starting_addr=_hum_reg, register_qty=_hum_qty, signed=_hum_signed)
            else:
                hvals = _serial.read_holding_registers(slave_addr=_slave_addr, starting_addr=_hum_reg, register_qty=_hum_qty, signed=_hum_signed)
            hraw, hval = _decode_vals(hvals, _hum_format, _hum_signed, _hum_scale)
            _last_hum_raw = hraw
            _last_hum = hval
            _last_hum_ok = True
        except Exception:
            _last_hum_ok = False


def get_status():
    return {
        "enabled": _enabled,
        "ok": _last_ok,
        "value_c": _last_value,
        "raw": _last_raw,
        "last_update_s": int(_last_ts) if _last_ts else None,
        "errors": _err_count,
        "slave_addr": _slave_addr,
        "reg_addr": _reg_addr,
        "func": "IREG" if _use_input_regs else "HREG",
        "scale": _scale,
        "format": _format,
        "humidity": {
            "enabled": _hum_enable,
            "ok": _last_hum_ok,
            "value_pct": _last_hum,
            "raw": _last_hum_raw,
            "reg_addr": _hum_reg,
            "scale": _hum_scale,
            "format": _hum_format,
        }
    }


