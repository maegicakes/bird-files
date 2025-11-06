# -*- coding: utf-8 -*-
import time
import board
import busio
from psycopg.rows import tuple_row
from adafruit_ina260 import INA260
import subprocess

import psycopg
import psycopg.rows
from psycopg.rows import tuple_row
import socket 
from datetime import datetime, timezone


DATABASE_URL="postgres://tsdbadmin:wzku9xbumxe8cidn@trydoj21xe.fvcwzcsqql.tsdb.cloud.timescale.com:37463/tsdb"
DEVICE_ID = socket.gethostname()
print(DEVICE_ID)

INSERT_SQL = """
INSERT INTO pi_heartbeats (time, device_id, voltage, current, power, soc_pct, cpu_temp)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

# DB helpers
def open_conn():
    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=tuple_row)

def insert_heartbeat(conn, when_utc, device_id, voltage_v, current_a, power_w, est_batt_p, cpu_temp_c):
    with conn.cursor() as cur:
        cur.execute(
            INSERT_SQL,
            (when_utc, device_id, voltage_v, current_a, power_w, est_batt_p, cpu_temp_c),
        )


# initialising I2C and sensor
i2c = busio.I2C(board.SCL, board.SDA)
ina = INA260(i2c, address=0x40)
# change address?

# 25c resting-voltage table for 12v yuasa sla (approx)
v_soc_table = [
    (12.90, 100),
    (12.70,  90),
    (12.50,  75),
    (12.40,  60),
    (12.20,  50),
    (12.00,  25),
    (11.80,  10),
    (11.50,   0),
]

def soc_from_voltage(v):
    for threshold, soc in v_soc_table:
        if v >= threshold:
            return soc
    return 0

def get_cpu_temp():
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        return float(out.replace("temp=", "").replace("'C\n", ""))
    except Exception:
        return None

print("reading ina260 values... press ctrl+c to stop.")

db_connection = None 
backoff_time = 1.0 
while True:
    try:
        if db_connection is None:
            db_connection = open_conn()
            backoff_time = 1.0
        
        voltage = float(ina.voltage)
        current = float(ina.current) / 1000.0  # mA? A
        power = float(ina.power) / 1000.0      # mW? W
        soc_pct = soc_from_voltage(voltage)
        cpu_temp = get_cpu_temp()

        print(f"voltage: {voltage:.2f} V | current: {current:.3f} A | power: {power:.3f} W | est batt: {soc_pct:3d}% | cpu temp: {cpu_temp:.1f} degC")
        now_utc = datetime.now()
        insert_heartbeat(db_connection, now_utc, DEVICE_ID, voltage, current, power, soc_pct, cpu_temp)
        
        time.sleep(600)
    
    except KeyboardInterrupt:
        break

    except Exception as e:
        print(f"[db/read error] {e}. retrying in {backoff_time:.1f}s")
        try:
            if db_connection is not None:
                db_connection.close()
        except Exception:
            pass

        db_connection = None
        time.sleep(backoff_time)
        backoff_time = min(backoff_time * 2, 30)
        
