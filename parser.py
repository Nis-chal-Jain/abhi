"""Parse one-second ESP32 serial reports."""

from __future__ import annotations

import re
import time
from typing import Optional

from analysis import Sample

PPG_HR = re.compile(r"HR\s+(\d+(?:\.\d+)?)\s*bpm")
PPG_HR_BLANK = re.compile(r"HR\s+--")
PPG_RMSSD = re.compile(r"HRV\(RMSSD\)\s+(\d+(?:\.\d+)?)\s*ms")
PPG_SPO2 = re.compile(r"SpO2\s+(\d+(?:\.\d+)?)\s*%")
PPG_IR = re.compile(r"IR=(\d+)")

EEG_DELTA = re.compile(r"Delta\s+([\d.]+)\s*Hz\s*\(([\d.]+)\s*uV\)")
EEG_THETA = re.compile(r"Theta\s+([\d.]+)\s*Hz\s*\(([\d.]+)\s*uV\)")
EEG_ALPHA = re.compile(r"Alpha\s+([\d.]+)\s*Hz\s*\(([\d.]+)\s*uV\)")
EEG_BETA = re.compile(r"Beta\s+([\d.]+)\s*Hz\s*\(([\d.]+)\s*uV\)")
EEG_GAMMA = re.compile(r"Gamma\s+([\d.]+)\s*Hz\s*\(([\d.]+)\s*uV\)")
EEG_PP = re.compile(r"pk-pk\s+([\d.]+)\s*uV")

IMU_RE = re.compile(
    r"X\s+([-\d.]+)\s*g\s*\|\s*Y\s+([-\d.]+)\s*g\s*\|\s*Z\s+([-\d.]+)\s*g\s*\|\s*noise\(SD\)\s+([\d.]+)\s*g\s*\[(moving|still)\]"
)
TEMP_RE = re.compile(r"TEMP\s*:\s*([-\d.]+)\s*C")


class SerialParser:
    def __init__(self) -> None:
        self.sample = Sample(t=time.time())

    def push_line(self, line: str) -> Optional[Sample]:
        raw = line.strip()
        if not raw:
            return None
        if raw.startswith("-----"):
            done = self.sample
            done.t = time.time()
            self.sample = Sample(t=time.time())
            # First separator has empty fields - skip incomplete frames
            if done.ppg_status == "ok" and done.hr is None and not done.eeg_ok and done.temp_c is None:
                if done.ppg_ok and not done.finger:
                    return done
                return None
            return done
        if raw.startswith("PPG"):
            self._ppg(raw)
        elif raw.startswith("EEG"):
            self._eeg(raw)
        elif raw.startswith("IMU"):
            self._imu(raw)
        elif raw.startswith("TEMP"):
            self._temp(raw)
            done = self.sample
            done.t = time.time()
            self.sample = Sample(t=time.time())
            return done
        return None

    def _ppg(self, line: str) -> None:
        s = self.sample
        if "not found" in line.lower():
            s.ppg_ok = False
            s.finger = False
            s.ppg_status = "missing"
            return
        ir = PPG_IR.search(line)
        if ir:
            s.ir = float(ir.group(1))
        if "place finger" in line.lower():
            s.finger = False
            s.ppg_status = "no_finger"
            s.hr = None
            s.rmssd = None
            s.spo2 = None
            return
        s.finger = True
        s.ppg_ok = True
        s.ppg_status = "ok"
        if PPG_HR_BLANK.search(line):
            s.hr = None
        else:
            m = PPG_HR.search(line)
            if m:
                s.hr = float(m.group(1))
        m = PPG_RMSSD.search(line)
        s.rmssd = float(m.group(1)) if m else None
        m = PPG_SPO2.search(line)
        s.spo2 = float(m.group(1)) if m else None

    def _eeg(self, line: str) -> None:
        s = self.sample
        if "warming" in line.lower():
            s.eeg_warming = True
            s.eeg_ok = False
            return
        if "no signal" in line.lower():
            s.eeg_ok = False
            s.eeg_warming = False
            return
        s.eeg_warming = False
        s.eeg_ok = True
        s.eeg_saturated = "SATURATED" in line
        for name, rx in (
            ("delta", EEG_DELTA),
            ("theta", EEG_THETA),
            ("alpha", EEG_ALPHA),
            ("beta", EEG_BETA),
            ("gamma", EEG_GAMMA),
        ):
            m = rx.search(line)
            if m:
                s.band_hz[name] = float(m.group(1))
                s.band_uv[name] = float(m.group(2))
        m = EEG_PP.search(line)
        if m:
            s.eeg_pp = float(m.group(1))

    def _imu(self, line: str) -> None:
        s = self.sample
        if "not found" in line.lower():
            s.imu_ok = False
            return
        m = IMU_RE.search(line)
        if not m:
            return
        s.ax = float(m.group(1))
        s.ay = float(m.group(2))
        s.az = float(m.group(3))
        s.motion_noise = float(m.group(4))
        s.moving = m.group(5) == "moving"
        s.imu_ok = True

    def _temp(self, line: str) -> None:
        s = self.sample
        if "not found" in line.lower():
            s.temp_ok = False
            s.temp_c = None
            return
        m = TEMP_RE.search(line)
        if m:
            s.temp_c = float(m.group(1))
            s.temp_ok = True
