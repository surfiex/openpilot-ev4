#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV4 SUPER LIVE ANALYZER
CAN0 + CAN1 RAW(최근40줄) + carState + radarState + 10초 주기 RAW LOG 저장

설치:
  openpilot/selfdrive/debug/ev4/ev4_live_analyze.py

실행:
  $ PYTHONPATH=. ./selfdrive/debug/ev4/ev4_live_analyze.py
"""

import os
import sys
import time
import datetime
import threading
from collections import deque

from cereal import messaging


# ===============================
# RAW BUFFER (최근 40줄)
# ===============================
RAW_BUFFER_SIZE = 40
raw_buffer = deque(maxlen=RAW_BUFFER_SIZE)

# 저장 주기
LOG_INTERVAL = 10    # seconds


# ===============================
# RAW LOG 저장 쓰레드
# ===============================
def log_writer_thread(log_dir, stop_event):
  """
  10초마다 raw_buffer의 내용을 새로운 파일로 저장
  """
  if log_dir is None:
    return

  os.makedirs(log_dir, exist_ok=True)

  last_save = 0
  while not stop_event.is_set():
    now = time.time()
    if now - last_save >= LOG_INTERVAL and len(raw_buffer) > 0:
      ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

      # bus0
      path0 = os.path.join(log_dir, f"{ts}_can0.log")
      # bus1
      path1 = os.path.join(log_dir, f"{ts}_can1.log")

      with open(path0, "w") as f0, open(path1, "w") as f1:
        for b, addr, dat in list(raw_buffer):
          line = f"{ts} bus={b} addr=0x{addr:X} dat={dat}\n"
          if b == 0:
            f0.write(line)
          elif b == 1:
            f1.write(line)

      last_save = now

    time.sleep(0.5)


# ===============================
# RAW CAN 수집 쓰레드
# ===============================
def raw_collector(can_sock, stop_event):
  """
  raw CAN 데이터를 실시간 수집하여 raw_buffer에 저장
  """
  while not stop_event.is_set():
    msg = messaging.recv_one(can_sock)
    if msg is None or msg.which() != "can":
      continue

    now = time.time()
    for c in msg.can:
      bus = getattr(c, "src", 0)
      dat_hex = c.dat.hex()

      raw_buffer.append((bus, c.address, dat_hex))


# ===============================
# MAIN ANALYZER
# ===============================
def main():
  log_dir = "/data/ev4_logs"

  # Socks
  cs_sock = messaging.sub_sock("carState", conflate=True)
  rs_sock = messaging.sub_sock("radarState", conflate=True)
  can_sock = messaging.sub_sock("can", conflate=False)

  # stop flag
  stop_event = threading.Event()

  # 쓰레드 시작: raw 수집 + log 저장
  t_raw = threading.Thread(target=raw_collector, args=(can_sock, stop_event), daemon=True)
  t_log = threading.Thread(target=log_writer_thread, args=(log_dir, stop_event), daemon=True)
  t_raw.start()
  t_log.start()

  last_ui = 0

  last_cs = None
  last_rs = None

  try:
    while True:
      # 받기
      msg = messaging.recv_one(cs_sock)
      if msg is not None and msg.which() == "carState":
        last_cs = msg.carState

      msg = messaging.recv_one(rs_sock)
      if msg is not None and msg.which() == "radarState":
        last_rs = msg.radarState

      # UI 업데이트
      if time.time() - last_ui < 0.2:
        continue
      last_ui = time.time()

      os.system("clear")
      print("==================== EV4 REALTIME CAN ANALYZER ====================\n")

      # ================= RAW CAN ==================
      print(">>> RAW CAN (최근 40줄)")
      if len(raw_buffer) == 0:
        print("  아직 CAN 메시지가 없습니다.\n")
      else:
        for (b, addr, dat) in list(raw_buffer)[-RAW_BUFFER_SIZE:]:
          print(f"  bus{b}  0x{addr:03X}  {dat}")
      print()

      # ================= CAR STATE ==================
      print(">>> CAR STATE")
      if last_cs is None:
        print("  carState 수신X\n")
      else:
        cs = last_cs
        print(f"  v_ego: {cs.vEgo:.3f} m/s")
        print(f"  steering_angle: {getattr(cs,'steeringAngleDeg','N/A')}")
        print(f"  steering_rate:  {getattr(cs,'steeringRateDeg','N/A')}")
        print(f"  brake_pressed:  {cs.brakePressed}")
        print(f"  gas_pressed:    {cs.gasPressed}")
        print()

      # ================= LEAD VEHICLE ==================
      print(">>> RADAR LEAD VEHICLE")
      if last_rs is None:
        print("  radarState 수신X\n")
      else:
        lead = getattr(last_rs, "leadOne", None)
        if lead is None or not lead.status:
          print("  lead 없음\n")
        else:
          print(f"  lead_distance:   {lead.dRel} m")
          print(f"  lead_rel_speed:  {lead.vRel} m/s\n")

      print("==================================================================")
      print("CTRL+C로 종료 (10초마다 RAW LOG 저장됨)")
      print()

  except KeyboardInterrupt:
    stop_event.set()
    print("\n종료 중...")

  finally:
    stop_event.set()
    time.sleep(0.5)
    print("완료.")


if __name__ == "__main__":
  main()
