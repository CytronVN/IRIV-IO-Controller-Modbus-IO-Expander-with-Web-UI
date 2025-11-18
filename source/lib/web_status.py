# SPDX-FileCopyrightText: 2025
#
# SPDX-License-Identifier: MIT
#
"""
Simple Web Status server for IRIV-IOC using CircuitPython HTTPServer.
Serves HTML at "/" and JSON at "/status.json".
Works only in MODBUS TCP mode; no-ops in RTU mode or if HTTP libs unavailable.
"""

import os
import time
import json
import microcontroller

import iriv_ioc_hal as Hal
import iriv_ioc_modbus as Modbus
import rs485_sensor as RS485


_enabled = False
_pool = None
_http_server = None
_start_monotonic = time.monotonic()

_have_httpserver = False
try:
    # CircuitPython HTTPServer works with socketpool (Wiznet5k)
    from adafruit_httpserver import Server, Request, Response, GET, JSONResponse
    _have_httpserver = True
except Exception:
    _have_httpserver = False


def _init_server():
    global _enabled, _pool, _http_server
    try:
        # Only enable when running in TCP mode (Ethernet available) and libs present
        if os.getenv("MODBUS_MODE") == "RTU":
            _enabled = False
            return
        if not _have_httpserver:
            _enabled = False
            return
        # Optional gate from settings
        enable = True
        try:
            val = os.getenv("WEBSERVER_ENABLE")
            if val is not None:
                s = str(val).strip().lower()
                enable = (s in ("1", "true", "yes", "on"))
        except Exception:
            enable = True
        if not enable:
            _enabled = False
            return
        # Reuse socket pool from Modbus TCP setup
        _pool = getattr(Modbus, "sockpool", None)
        if _pool is None:
            _enabled = False
            return
        # Port from settings (default 80)
        port = 80
        try:
            pv = os.getenv("WEBSERVER_PORT")
            if pv is not None:
                port = int(pv)
        except Exception:
            port = 80
        # Create server
        _http_server = Server(_pool, "/")
        
        @_http_server.route("/", GET)
        def index(request: Request):  # noqa: N802
            status = _read_status()
            body = _html_page(status)
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        @_http_server.route("/status.json", GET)
        def status_json(request: Request):  # noqa: N802
            status = _read_status()
            return JSONResponse(request, status)
        
        # Toggle routes for Digital Outputs
        @_http_server.route("/toggle_do0", GET)
        def do0_toggle(request: Request):  # noqa: N802
            try:
                newv = 0 if Hal.dout0.value else 1
                Hal.dout0.value = newv
                Modbus.client.set_coil(Modbus.DO0_ADD, newv)
            except Exception:
                pass
            body = "<!doctype html><meta http-equiv='refresh' content='0;url=/'><a href='/'>Back</a>"
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        @_http_server.route("/toggle_do1", GET)
        def do1_toggle(request: Request):  # noqa: N802
            try:
                newv = 0 if Hal.dout1.value else 1
                Hal.dout1.value = newv
                Modbus.client.set_coil(Modbus.DO1_ADD, newv)
            except Exception:
                pass
            body = "<!doctype html><meta http-equiv='refresh' content='0;url=/'><a href='/'>Back</a>"
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        @_http_server.route("/toggle_do2", GET)
        def do2_toggle(request: Request):  # noqa: N802
            try:
                newv = 0 if Hal.dout2.value else 1
                Hal.dout2.value = newv
                Modbus.client.set_coil(Modbus.DO2_ADD, newv)
            except Exception:
                pass
            body = "<!doctype html><meta http-equiv='refresh' content='0;url=/'><a href='/'>Back</a>"
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        @_http_server.route("/toggle_do3", GET)
        def do3_toggle(request: Request):  # noqa: N802
            try:
                newv = 0 if Hal.dout3.value else 1
                Hal.dout3.value = newv
                Modbus.client.set_coil(Modbus.DO3_ADD, newv)
            except Exception:
                pass
            body = "<!doctype html><meta http-equiv='refresh' content='0;url=/'><a href='/'>Back</a>"
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        @_http_server.route("/toggle_led", GET)
        def led_toggle(request: Request):  # noqa: N802
            try:
                Hal.led.value = 0 if Hal.led.value else 1
            except Exception:
                pass
            body = "<!doctype html><meta http-equiv='refresh' content='0;url=/'><a href='/'>Back</a>"
            return Response(request, body=body, content_type="text/html; charset=utf-8")
        
        # Start the server; bind to device IP to avoid None-host incompatibilities
        ip_str = None
        try:
            eth = getattr(Modbus, "eth", None)
            if eth is not None:
                ip_str = eth.pretty_ip(eth.ip_address)
        except Exception:
            ip_str = None
        _http_server.start(host=ip_str, port=port)
        _enabled = True
    except Exception:
        # If anything goes wrong, disable web server gracefully
        _enabled = False
        _pool = None
        _http_server = None


def _fmt_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if days:
        return "{}d {:02d}:{:02d}:{:02d}".format(days, hours, minutes, secs)
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)


def _read_status() -> dict:
    # Device/network info
    eth = getattr(Modbus, "eth", None)
    hostname = getattr(Modbus, "hostname", None)
    mac = None
    ip = None
    link = None
    if eth is not None:
        try:
            mac = eth.pretty_mac(eth.mac_address)
        except Exception:
            mac = None
        try:
            ip = eth.pretty_ip(eth.ip_address)
        except Exception:
            ip = None
        try:
            link = bool(eth.link_status)
        except Exception:
            link = None
    # Uptime and temperature
    uptime_s = int(time.monotonic())
    cpu_temp_c = None
    try:
        cpu_temp_c = float(microcontroller.cpu.temperature)
    except Exception:
        cpu_temp_c = None
    # Supply voltage (best-effort)
    supply_mv = None
    try:
        supply_mv = int(Hal.SUPPLY_VOLTAGE)
    except Exception:
        supply_mv = None
    # Digital inputs and outputs
    dins = {
        "DI0":  int(Hal.din0.value),
        "DI1":  int(getattr(Hal, "count1", Hal.din1).count if getattr(Hal, "count1", None) is not None else int(Hal.din1.value)),
        "DI2":  int(Hal.din2.value),
        "DI3":  int(getattr(Hal, "count3", Hal.din3).count if getattr(Hal, "count3", None) is not None else int(Hal.din3.value)),
        "DI4":  int(Hal.din4.value),
        "DI5":  int(getattr(Hal, "count5", Hal.din5).count if getattr(Hal, "count5", None) is not None else int(Hal.din5.value)),
        "DI6":  int(Hal.din6.value),
        "DI7":  int(getattr(Hal, "count7", Hal.din7).count if getattr(Hal, "count7", None) is not None else int(Hal.din7.value)),
        "DI8":  int(Hal.din8.value),
        "DI9":  int(getattr(Hal, "count9", Hal.din9).count if getattr(Hal, "count9", None) is not None else int(Hal.din9.value)),
        "DI10": int(Hal.din10.value),
    }
    # For counters, also expose counts explicitly
    counters = {
        "COUNT1": int(getattr(Hal.count1, "count", 0)) if getattr(Hal, "count1", None) is not None else None,
        "COUNT3": int(getattr(Hal.count3, "count", 0)) if getattr(Hal, "count3", None) is not None else None,
        "COUNT5": int(getattr(Hal.count5, "count", 0)) if getattr(Hal, "count5", None) is not None else None,
        "COUNT7": int(getattr(Hal.count7, "count", 0)) if getattr(Hal, "count7", None) is not None else None,
        "COUNT9": int(getattr(Hal.count9, "count", 0)) if getattr(Hal, "count9", None) is not None else None,
    }
    douts = {
        "DO0": int(Hal.dout0.value),
        "DO1": int(Hal.dout1.value),
        "DO2": int(Hal.dout2.value),
        "DO3": int(Hal.dout3.value),
    }
    # Analog readings (best-effort)
    try:
        anv0 = int(Hal.an_read_voltage_mv(0))
        anv1 = int(Hal.an_read_voltage_mv(1))
    except Exception:
        anv0 = None
        anv1 = None
    try:
        ana0 = int(Hal.an_read_current_ua(0))
        ana1 = int(Hal.an_read_current_ua(1))
    except Exception:
        ana0 = None
        ana1 = None
    return {
        "device": {
            "model": "IRIV-IOC",
            "hostname": hostname,
            "mac": mac,
            "ip": ip,
            "link_up": link,
            "uptime_seconds": uptime_s,
            "uptime_hms": _fmt_uptime(uptime_s),
            "cpu_temp_c": cpu_temp_c,
            "supply_mv": supply_mv,
        },
        "io": {
            "din": dins,
            "dout": douts,
            "counters": counters,
            "an_voltage_mv": {"AN0": anv0, "AN1": anv1},
            "an_current_ua": {"AN0": ana0, "AN1": ana1},
        },
        "sensors": {
            "rs485": RS485.get_status(),
        },
    }


def _html_page(status: dict) -> str:
    dev = status.get("device", {})
    io = status.get("io", {})
    din = io.get("din", {})
    dout = io.get("dout", {})
    counters = io.get("counters", {})
    an_v = io.get("an_voltage_mv", {})
    an_a = io.get("an_current_ua", {})
    sensors = status.get("sensors", {})
    rs = sensors.get("rs485", {}) if isinstance(sensors, dict) else {}
    rs_h = rs.get("humidity", {}) if isinstance(rs.get("humidity", {}), dict) else {}
    # Refresh interval (seconds), configurable via settings
    try:
        refresh_sec = int(os.getenv("WEBSERVER_REFRESH_SEC") or 5)
        if refresh_sec < 1:
            refresh_sec = 1
    except Exception:
        refresh_sec = 5
    def badge(val):
        return '<span style="display:inline-block;padding:2px 8px;border-radius:10px;{}">{}</span>'.format(
            "background:#16a34a;color:#fff" if val else "background:#ef4444;color:#fff",
            "ON" if val else "OFF"
        )
    rows_di = "".join(
        "<tr><td>{}</td><td style='text-align:right'>{}</td></tr>".format(k, badge(bool(v)))
        for k, v in din.items()
    )
    rows_do = ""
    for k, v in dout.items():
        path = "/toggle_{}".format(k.lower())
        rows_do += "<tr><td>{}</td><td style='text-align:right'>{} <a href='{}' style='margin-left:8px'>Toggle</a></td></tr>".format(k, badge(bool(v)), path)
    rows_cnt = "".join(
        "<tr><td>{}</td><td style='text-align:right'>{}</td></tr>".format(k, ("" if v is None else v))
        for k, v in counters.items()
    )
    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{refresh}">
  <title>IRIV IO Controller Status</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 12px; color: #111827; }}
    h1 {{ font-size: 20px; margin: 0 0 12px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 12px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; background: #fff; }}
    .muted {{ color: #6b7280; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ padding: 4px 0; border-bottom: 1px solid #f3f4f6; }}
    .k {{ color: #374151; }}
    .v {{ text-align: right; color: #111827; }}
  </style>
</head>
<body>
  <h1>IRIV IO Controller Status</h1>
  <div class="grid">
    <div class="card">
      <div class="muted">Device</div>
      <table>
        <tr><td class="k">Model</td><td class="v">{model}</td></tr>
        <tr><td class="k">Hostname</td><td class="v">{hostname}</td></tr>
        <tr><td class="k">MAC</td><td class="v">{mac}</td></tr>
        <tr><td class="k">IP</td><td class="v">{ip}</td></tr>
        <tr><td class="k">Link</td><td class="v">{link}</td></tr>
        <tr><td class="k">Uptime</td><td class="v">{uptime}</td></tr>
        <tr><td class="k">CPU Temp</td><td class="v">{temp}</td></tr>
        <tr><td class="k">Supply</td><td class="v">{supply}</td></tr>
      </table>
    </div>
    <div class="card">
      <div class="muted">Digital Inputs</div>
      <table>{rows_di}</table>
    </div>
    <div class="card">
      <div class="muted">Digital Outputs</div>
      <table>{rows_do}</table>
    </div>
    <div class="card">
      <div class="muted">Counters</div>
      <table>{rows_cnt}</table>
    </div>
    <div class="card">
      <div class="muted">Analog</div>
      <table>
        <tr><td>AN0 Voltage (mV)</td><td style="text-align:right">{anv0}</td></tr>
        <tr><td>AN1 Voltage (mV)</td><td style="text-align:right">{anv1}</td></tr>
        <tr><td>AN0 Current (uA)</td><td style="text-align:right">{ana0}</td></tr>
        <tr><td>AN1 Current (uA)</td><td style="text-align:right">{ana1}</td></tr>
      </table>
    </div>
    <div class="card">
      <div class="muted">RS485 Sensor</div>
      <table>
        <tr><td class="k">Enabled</td><td class="v">{rs_en}</td></tr>
        <tr><td class="k">Status</td><td class="v">{rs_ok}</td></tr>
        <tr><td class="k">Temperature</td><td class="v">{rs_temp}</td></tr>
        <tr><td class="k">Raw</td><td class="v">{rs_raw}</td></tr>
        <tr><td class="k">Slave/Reg</td><td class="v">{rs_addr}</td></tr>
        <tr><td class="k">Humidity</td><td class="v">{rs_hum}</td></tr>
      </table>
    </div>
  </div>
  <div class="muted" style="margin-top:8px">
    LED: <a href="/toggle_led">Toggle</a>
  </div>
  <div class="muted" style="margin-top:8px">JSON: /status.json</div>
</body>
</html>""".format(
        model=dev.get("model") or "",
        hostname=dev.get("hostname") or "",
        mac=dev.get("mac") or "",
        ip=dev.get("ip") or "",
        link="UP" if dev.get("link_up") else "DOWN" if dev.get("link_up") is not None else "",
        uptime=dev.get("uptime_hms") or "",
        temp=("{:.1f} °C".format(dev["cpu_temp_c"]) if isinstance(dev.get("cpu_temp_c"), (int, float)) else ""),
        supply=("{} mV".format(dev["supply_mv"]) if isinstance(dev.get("supply_mv"), int) else ""),
        rows_di=rows_di,
        rows_do=rows_do,
        rows_cnt=rows_cnt,
        anv0=an_v.get("AN0"),
        anv1=an_v.get("AN1"),
        ana0=an_a.get("AN0"),
        ana1=an_a.get("AN1"),
        refresh=refresh_sec,
        rs_en="YES" if rs.get("enabled") else "NO",
        rs_ok="OK" if rs.get("ok") else "N/A" if not rs.get("enabled") else "ERR",
        rs_temp=("{:.1f} °C".format(rs["value_c"]) if isinstance(rs.get("value_c"), (int, float)) else ""),
        rs_raw=(rs.get("raw") if rs.get("raw") is not None else ""),
        rs_addr=("{} @ {}".format(rs.get("reg_addr"), rs.get("slave_addr")) if rs.get("enabled") else ""),
        rs_hum=("{:.1f} %RH".format(rs_h.get("value_pct")) if isinstance(rs_h.get("value_pct"), (int, float)) else ""),
    )
    return html


def process():
    if not _enabled:
        _init_server()
        return
    # Poll HTTP server (non-blocking)
    try:
        _http_server.poll()
    except Exception:
        # If server misbehaves, disable to keep MODBUS alive
        pass


