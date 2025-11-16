#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV4 LIVE ANALYZER (CAN0 + CAN1 FULL VERSION)
--------------------------------------------
openpilot 기반 EV4 포팅용 실시간 CAN + carState 분석기

특징:
 - CAN0 + CAN1 프레임 실시간 표시
 - raw CAN 로그 저장 (--log-dir)
 - carState의 속도/조향/페달/도어/안전/ADAS 정보 표시
 - radarState 기반 lead_distance / lead_rel_speed 표시
 - EV4에서 아직 미구현된 신호는 N/A 또는 TODO 로 표기됨

설치 위치 권장:
   openpilot/selfdrive/debug/ev4/ev4_live_analyze.py

실행:
   (openpilot root에서)
   $ PYTHONPATH=. ./selfdrive/debug/ev4/ev4_live_analyze.py
   $ PYTHONPATH=. ./selfdrive/debug/ev4/ev4_live_analyze.py --log-dir /data/ev4_logs
"""

import argparse
import os
import sys
import time
import datetime
from cereal import messaging


# ------------------------------
# Helper function
# ------------------------------
def hex_bytes(dat: bytes) -> str:
  return dat.hex()


def parse_args():
  p = argparse.ArgumentParser("EV4 live analyzer")
  p.add_argument("--log-dir",
                default=None,
                help="지정하면 CAN0/CAN1 RAW 로그를 저장 (예: /data/ev4_logs)")
  p.add_argument("--interval",
                type=float,
                default=0.2,
                help="UI 갱신 주기 (기본 0.2초)")
  p.add_argument("--no-clear",
                action="store_true",
                help="터미널 clear 사용 안 함")
  return p.parse_args()


# ------------------------------
# CAN Logger
# ------------------------------
class CANLogger:
  def __init__(self, log_dir):
    self.log_dir = log_dir
    self.files = {}
    if log_dir:
      os.makedirs(log_dir, exist_ok=True)
      for bus in (0, 1):
        path = os.path.join(log_dir, f"ev4_can{bus}.log")
        self.files[bus] = open(path, "a", buffering=1)

  def log(self, t, bus, addr, dat):
    if self.log_dir is None:
      return
    if bus not in self.files:
      return
    ts = datetime.datetime.fromtimestamp(t).isoformat()
    self.files[bus].write(f"{ts} bus={bus} addr=0x{addr:X} dat={hex_bytes(dat)}\n")

  def close(self):
    for f in self.files.values():
      f.close()


# ------------------------------
# Main
# ------------------------------
def main():
  args = parse_args()

  cs_sock = messaging.sub_sock("carState", conflate=True)
  rs_sock = messaging.sub_sock("radarState", conflate=True)
  can_sock = messaging.sub_sock("can", conflate=False)

  poller = messaging.Poller((cs_sock, rs_sock, can_sock))

  can_stats = {
    0: {"frames": 0, "last_addr": None, "last_time": 0.0},
    1: {"frames": 0, "last_addr": None, "last_time": 0.0},
  }

  last_cs = None
  last_rs = None

  logger = CANLogger(args.log_dir)
  last_ui = 0

  try:
    while True:
      for sock in poller.poll(100):
        msg = messaging.recv_one(sock)
        if msg is None:
          continue

        now = time.time()

        if sock is cs_sock:
          if msg.which() == "carState":
            last_cs = msg.carState

        elif sock is rs_sock:
          if msg.which() == "radarState":
            last_rs = msg.radarState

        elif sock is can_sock:
          if msg.which() != "can":
            continue
          for c in msg.can:
            bus = getattr(c, "src", 0)
            if bus in can_stats:
              can_stats[bus]["frames"] += 1
              can_stats[bus]["last_addr"] = c.address
              can_stats[bus]["last_time"] = now
              logger.log(now, bus, c.address, c.dat)

      if time.time() - last_ui < args.interval:
        continue
      last_ui = time.time()

      if not args.no_clear:
        os.system("clear")

      print("========== EV4 LIVE ANALYZE (CAN0 + CAN1) ==========")
      print(f"Time: {datetime.datetime.now().isoformat()}")
      print()

      # ----------------------
      # CAN Bus Stats
      # ----------------------
      print("[CAN BUS STATS]")
      for bus in (0, 1):
        s = can_stats[bus]
        age = time.time() - s["last_time"] if s["last_time"] else None
        age_s = f"{age:.2f}s ago" if age else "N/A"
        if s["last_addr"] is None:
          print(f"  BUS{bus}: frames={s['frames']}  last_addr=N/A  last_msg_age=N/A")
        else:
          print(f"  BUS{bus}: frames={s['frames']}  last_addr=0x{s['last_addr']:03X}  last_msg_age={age_s}")
      print()

      # ----------------------
      # CarState signals
      # ----------------------
      print("[CAR-STATE SIGNALS]")
      if last_cs is None:
        print("  carState 수신 안됨")
      else:
        cs = last_cs

        # 기본
        print("  [기본 주행]")
        print(f"    v_ego               : {getattr(cs,'vEgo', 'N/A')}")
        print(f"    a_ego               : {getattr(cs,'aEgo','N/A')}")
        print(f"    yaw_rate            : {getattr(cs,'yawRate','N/A')}")
        print()

        # 휠 속도
        ws = getattr(cs, "wheelSpeeds", None)
        print("  [휠 속도]")
        if ws:
          print(f"    FL: {ws.fl}, FR: {ws.fr}")
          print(f"    RL: {ws.rl}, RR: {ws.rr}")
        else:
          print("    wheelSpeeds: N/A")
        print()

        # 조향/페달
        print("  [조향/페달]")
        print(f"    steering_angle      : {getattr(cs,'steeringAngleDeg','N/A')}")
        print(f"    steering_rate       : {getattr(cs,'steeringRateDeg','N/A')}")
        print(f"    brake_pressed       : {getattr(cs,'brakePressed','N/A')}")
        print(f"    gas_pressed         : {getattr(cs,'gasPressed','N/A')}")
        print()

        # 기어/램프
        print("  [기어/램프]")
        print(f"    gear_shifter        : {getattr(cs,'gearShifter','N/A')}")
        print(f"    left_blinker        : {getattr(cs,'leftBlinker','N/A')}")
        print(f"    right_blinker       : {getattr(cs,'rightBlinker','N/A')}")
        print(f"    parking_brake       : {getattr(cs,'parkingBrake','N/A')}")
        print()

        # 도어/벨트
        print("  [도어/벨트]")
        print(f"    door_open(any)      : {getattr(cs,'doorOpen','N/A')}")
        print(f"    seatbelt_unlatched  : {getattr(cs,'seatbeltUnlatched','N/A')}")
        print("    door_fl/fr/rl/rr    : N/A (TODO: EV4 DBC 매핑 후 구현)")
        print("    seatbelt_driver/pass: N/A (TODO: EV4 DBC 매핑 후 구현)")
        print()

        # ADAS / 안전
        print("  [ADAS/안전]")
        print(f"    FCW                 : {getattr(cs,'forwardCollisionWarning','N/A')}")
        print(f"    blindspot_left      : {getattr(cs,'leftBlindspot','N/A')}")
        print(f"    blindspot_right     : {getattr(cs,'rightBlindspot','N/A')}")
        print("    lane_detected_left/right : N/A (TODO)")
        print()

      # ----------------------
      # Radar lead vehicle
      # ----------------------
      print("[LEAD VEHICLE / RADARSTATE]")
      if last_rs is None:
        print("  radarState 수신 안됨")
      else:
        lead = getattr(last_rs, "leadOne", None)
        if lead is None or not getattr(lead, "status", False):
          print("  lead 없음")
        else:
          print(f"  lead_distance (m)    : {lead.dRel}")
          print(f"  lead_rel_speed (m/s) : {lead.vRel}")
      print("====================================================")

  except KeyboardInterrupt:
    print("\n종료합니다.")
  finally:
    logger.close()


if __name__ == "__main__":
  sys.exit(main())
