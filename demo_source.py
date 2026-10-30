"""Realistic fake sensor stream for Demo Mode."""

from __future__ import annotations

import math
import random
import time

from analysis import Sample


class DemoSource:
    def __init__(self) -> None:
        self.t0 = time.time()
        self._hr_base = 68.0
        self._temp = 33.15
        self._seed = random.random() * 10

    def sample(self, cal_phase: str = "idle") -> Sample:
        t = time.time() - self.t0
        breathe = math.sin(t * 0.22)
        wander = math.sin(t * 0.031 + self._seed)
        moving = (int(t) % 47) in (0, 1) and t > 20
        hr = self._hr_base + 4.5 * breathe + 2.0 * wander + random.uniform(-0.6, 0.6)
        if moving:
            hr += 8
        rmssd = 42 + 10 * math.sin(t * 0.05) - (8 if moving else 0) + random.uniform(-2, 2)
        self._temp += random.uniform(-0.012, 0.01) + 0.0015 * math.sin(t * 0.02)
        self._temp = max(32.4, min(34.2, self._temp))

        # Eyes-closed check: stronger alpha. Eyes-open: weaker alpha.
        if cal_phase == "eyes_closed":
            alpha = 22 + random.uniform(-1.5, 1.5)
            beta = 6 + random.uniform(-0.5, 0.5)
            theta = 9 + random.uniform(-0.8, 0.8)
        elif cal_phase == "eyes_open":
            alpha = 9 + random.uniform(-1.0, 1.0)
            beta = 11 + random.uniform(-0.8, 0.8)
            theta = 8 + random.uniform(-0.6, 0.6)
        else:
            alpha = 12 + 3 * math.sin(t * 0.07) + random.uniform(-0.7, 0.7)
            beta = 8.5 + 2.2 * math.sin(t * 0.045 + 1) + random.uniform(-0.5, 0.5)
            theta = 9.5 + 2.0 * math.sin(t * 0.04 + 2) + random.uniform(-0.5, 0.5)

        delta = 14 + 2 * math.sin(t * 0.03) + random.uniform(-0.4, 0.4)
        gamma = 3.2 + 0.6 * math.sin(t * 0.09) + random.uniform(-0.2, 0.2)

        s = Sample(t=time.time())
        s.ppg_ok = True
        s.finger = True
        s.hr = hr
        s.rmssd = max(12.0, rmssd)
        s.spo2 = 97 + random.choice([0, 0, 1])
        s.ir = 120000 + 8000 * breathe
        s.eeg_ok = True
        s.eeg_warming = False
        s.eeg_saturated = False
        s.band_hz = {
            "delta": 1.8 + 0.2 * math.sin(t * 0.1),
            "theta": 5.8 + 0.3 * math.sin(t * 0.12),
            "alpha": 10.1 + 0.4 * math.sin(t * 0.08),
            "beta": 18.5 + 1.2 * math.sin(t * 0.11),
            "gamma": 36.0 + 1.5 * math.sin(t * 0.13),
        }
        s.band_uv = {
            "delta": max(1.0, delta),
            "theta": max(1.0, theta),
            "alpha": max(1.0, alpha),
            "beta": max(1.0, beta),
            "gamma": max(0.5, gamma),
        }
        s.eeg_pp = 40 + 8 * math.sin(t * 0.06)
        mag = 1.0 + (0.12 if moving else 0.01 * random.random())
        s.ax = 0.02 * math.sin(t) + (0.15 if moving else 0)
        s.ay = 0.01 * math.cos(t * 1.3)
        s.az = mag
        s.motion_noise = 0.12 if moving else 0.012 + 0.004 * random.random()
        s.moving = moving
        s.imu_ok = True
        s.temp_c = self._temp
        s.temp_ok = True
        return s
