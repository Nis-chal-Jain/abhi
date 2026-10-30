"""Biosignal result engine. All scoring stays on the server."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import savgol_filter


BANDS = ("delta", "theta", "alpha", "beta", "gamma")
BAND_HZ = {
    "delta": "0.5-4 Hz",
    "theta": "4-8 Hz",
    "alpha": "8-13 Hz",
    "beta": "13-30 Hz",
    "gamma": "30-45 Hz",
}

AUTONOMIC_NEED_S = 180.0
ATTENTION_WINDOW_S = 20.0
HISTORY_MAX = 360


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ema(prev: Optional[float], value: float, alpha: float) -> float:
    if prev is None or math.isnan(prev):
        return value
    return alpha * value + (1.0 - alpha) * prev


@dataclass
class Sample:
    t: float
    hr: Optional[float] = None
    rmssd: Optional[float] = None
    spo2: Optional[float] = None
    ir: Optional[float] = None
    finger: bool = False
    ppg_ok: bool = True
    ppg_status: str = "ok"
    eeg_ok: bool = False
    eeg_warming: bool = False
    eeg_saturated: bool = False
    eeg_pp: Optional[float] = None
    band_hz: Dict[str, float] = field(default_factory=dict)
    band_uv: Dict[str, float] = field(default_factory=dict)
    ax: Optional[float] = None
    ay: Optional[float] = None
    az: Optional[float] = None
    motion_noise: Optional[float] = None
    moving: bool = False
    imu_ok: bool = True
    temp_c: Optional[float] = None
    temp_ok: bool = True


class AnalysisEngine:
    def __init__(self) -> None:
        self._vigilance: Optional[float] = None
        self._attention: Optional[float] = None
        self._ei_hist: Deque[Tuple[float, float]] = deque(maxlen=240)
        self._rmssd_hist: Deque[Tuple[float, float]] = deque(maxlen=600)
        self._temp_hist: Deque[Tuple[float, float]] = deque(maxlen=600)
        self._hr_hist: Deque[Tuple[float, float]] = deque(maxlen=600)
        self._history: Deque[Dict[str, Any]] = deque(maxlen=HISTORY_MAX)
        self._hr_good_s = 0.0
        self._last_hr_tick: Optional[float] = None
        self._cal_phase = "idle"
        self._cal_ends = 0.0
        self._alpha_ec: List[float] = []
        self._alpha_eo: List[float] = []
        self._alpha_suppression: Optional[float] = None
        self._calibrated = False
        self._band_peak: Dict[str, float] = {b: 8.0 for b in BANDS}
        self._wave_phase = 0.0
        self._ppg_phase = 0.0
        self._last_sample: Optional[Sample] = None

    def start_calibration(self) -> None:
        self._cal_phase = "eyes_closed"
        self._cal_ends = time.time() + 30.0
        self._alpha_ec = []
        self._alpha_eo = []

    def reset_calibration(self) -> None:
        self._cal_phase = "idle"
        self._cal_ends = 0.0
        self._alpha_ec = []
        self._alpha_eo = []

    def feed(self, sample: Sample) -> Dict[str, Any]:
        now = sample.t
        self._last_sample = sample
        self._update_calibration(sample)
        self._collect_streams(sample)

        moving = bool(sample.moving)
        eeg_bad = self._eeg_bad(sample)
        as_poor = self._calibrated and self._alpha_suppression is not None and self._alpha_suppression < 20.0

        vig_raw, vig_color, vig_meaning, vig_tip = self._vigilance_result(sample)
        self._vigilance = _ema(self._vigilance, vig_raw, 0.28) if vig_raw is not None else self._vigilance
        vig_score = None if self._vigilance is None else int(round(_clip(self._vigilance, 0, 100)))

        att_score, att_trend, att_label = self._attention_result(sample)
        if att_score is not None:
            self._attention = _ema(self._attention, att_score, 0.22)
        att_out = None if self._attention is None else int(round(_clip(self._attention, 0, 100)))

        auto = self._autonomic_result(now)

        confidence, quality_message, motion_warning = self._quality(
            sample, moving, eeg_bad, as_poor
        )

        bands_ui = []
        for name in BANDS:
            uv = float(sample.band_uv.get(name, 0.0) or 0.0)
            self._band_peak[name] = max(self._band_peak[name] * 0.995, uv, 4.0)
            level = _clip(uv / max(self._band_peak[name], 1e-6), 0.04, 1.0)
            bands_ui.append(
                {
                    "name": name.capitalize(),
                    "range": BAND_HZ[name],
                    "level": round(level, 3),
                    "microvolts": round(uv, 1),
                    "peak_hz": round(float(sample.band_hz.get(name, 0.0) or 0.0), 2),
                }
            )

        eeg_wave, ppg_wave = self._waveforms(sample)

        temp_vals = np.array([v for _, v in list(self._temp_hist)[-60:]], dtype=float)
        if temp_vals.size >= 9:
            win = min(9, temp_vals.size if temp_vals.size % 2 == 1 else temp_vals.size - 1)
            temp_vals = savgol_filter(temp_vals, window_length=max(5, win), polyorder=2)
        temp_line = [round(float(v), 3) for v in temp_vals]

        self._history.append(
            {
                "t": round(now, 2),
                "vigilance": vig_score,
                "attention": att_out,
                "mood": None,
                "autonomic": auto.get("score"),
            }
        )

        cal = self._calibration_payload(now)

        return {
            "server_time": now,
            "live": {
                "heart_rate": None if sample.hr is None else int(round(sample.hr)),
                "heart_ok": bool(sample.finger and sample.hr),
                "heart_note": self._heart_note(sample),
                "spo2": None if sample.spo2 is None else int(round(sample.spo2)),
                "eeg_bands": bands_ui,
                "temperature_c": None if sample.temp_c is None else round(sample.temp_c, 2),
                "temperature_trend": temp_line,
                "eeg_wave": eeg_wave,
                "ppg_wave": ppg_wave,
                "motion": {
                    "moving": moving,
                    "level": round(_clip((sample.motion_noise or 0.0) / 0.20, 0.0, 1.0), 3),
                    "x": sample.ax,
                    "y": sample.ay,
                    "z": sample.az,
                },
            },
            "quality": {
                "confidence": confidence,
                "message": quality_message,
                "motion_warning": motion_warning,
                "eeg_saturated": sample.eeg_saturated,
            },
            "results": {
                "vigilance": {
                    "score": vig_score,
                    "color": vig_color if vig_score is not None else "gray",
                    "meaning": vig_meaning,
                    "tip": vig_tip,
                    "confidence": confidence,
                },
                "attention": {
                    "trend": att_trend,
                    "label": att_label,
                    "score": att_out,
                    "note": "This marker is debated among researchers, so treat it as a gentle hint - confidence is low to moderate.",
                    "tip": self._attention_tip(att_trend),
                    "confidence": "Low to moderate",
                },
                "mood": {
                    "available": False,
                    "message": "Mood Lean needs two forehead electrodes",
                    "detail": "This reading needs a left and a right forehead sensor. Your current headset sends one brain-wave channel, so a mood lean cannot be shown.",
                    "tip": "Add a second forehead electrode (left and right) if you want this card to fill in.",
                    "confidence": "Not available",
                },
                "autonomic": auto,
            },
            "calibration": cal,
            "history": list(self._history)[-180:],
        }

    def _heart_note(self, sample: Sample) -> str:
        if not sample.ppg_ok:
            return "Heart sensor not found"
        if not sample.finger:
            return "Place your finger on the pulse sensor"
        if sample.hr is None:
            return "Finding your pulse..."
        return "Live"

    def _eeg_bad(self, sample: Sample) -> bool:
        if sample.eeg_warming or not sample.eeg_ok:
            return True
        if sample.eeg_saturated:
            return True
        if sample.eeg_pp is not None and (sample.eeg_pp < 8.0 or sample.eeg_pp > 400.0):
            return True
        return False

    def _update_calibration(self, sample: Sample) -> None:
        now = time.time()
        if self._cal_phase == "idle":
            return
        alpha = float(sample.band_uv.get("alpha", 0.0) or 0.0)
        if self._cal_phase == "eyes_closed":
            if sample.eeg_ok and not sample.moving:
                self._alpha_ec.append(alpha)
            if now >= self._cal_ends:
                self._cal_phase = "eyes_open"
                self._cal_ends = now + 30.0
        elif self._cal_phase == "eyes_open":
            if sample.eeg_ok and not sample.moving:
                self._alpha_eo.append(alpha)
            if now >= self._cal_ends:
                self._finish_calibration()

    def _finish_calibration(self) -> None:
        self._cal_phase = "done"
        ec = sum(self._alpha_ec) / max(len(self._alpha_ec), 1)
        eo = sum(self._alpha_eo) / max(len(self._alpha_eo), 1)
        if ec <= 1e-6:
            self._alpha_suppression = 0.0
        else:
            self._alpha_suppression = 100.0 * (ec - eo) / ec
        self._calibrated = True

    def _calibration_payload(self, now: float) -> Dict[str, Any]:
        remaining = max(0, int(math.ceil(self._cal_ends - time.time()))) if self._cal_phase in ("eyes_closed", "eyes_open") else 0
        prompts = {
            "idle": "Optional: run a one-minute check so we know the headband is making good contact.",
            "eyes_closed": "Close your eyes and stay still.",
            "eyes_open": "Open your eyes and look softly ahead. Stay still.",
            "done": "Check complete.",
        }
        as_txt = None
        if self._calibrated:
            if self._alpha_suppression is not None and self._alpha_suppression >= 20:
                as_txt = "Contact looks good."
            else:
                as_txt = "Low confidence: check electrode contact"
        return {
            "phase": self._cal_phase,
            "remaining_s": remaining,
            "prompt": prompts[self._cal_phase],
            "calibrated": self._calibrated,
            "contact_ok": bool(self._calibrated and (self._alpha_suppression or 0) >= 20),
            "summary": as_txt,
        }

    def _collect_streams(self, sample: Sample) -> None:
        now = sample.t
        if sample.temp_c is not None:
            self._temp_hist.append((now, sample.temp_c))
        if sample.finger and sample.hr and sample.hr > 0:
            self._hr_hist.append((now, sample.hr))
            if self._last_hr_tick is not None:
                dt = now - self._last_hr_tick
                if 0 < dt < 3:
                    self._hr_good_s += dt
            self._last_hr_tick = now
        else:
            self._last_hr_tick = None
        if sample.finger and sample.rmssd is not None:
            self._rmssd_hist.append((now, sample.rmssd))

    def _relative_power(self, sample: Sample) -> Optional[Dict[str, float]]:
        amps = np.array([float(sample.band_uv.get(name, 0.0) or 0.0) for name in BANDS], dtype=float)
        powers = np.square(amps)
        total = float(powers.sum())
        if total <= 1e-9:
            return None
        rel = powers / total
        return {name: float(rel[i]) for i, name in enumerate(BANDS)}

    def _vigilance_result(self, sample: Sample) -> Tuple[Optional[float], str, str, str]:
        if not sample.eeg_ok:
            return None, "gray", "Waiting for a brain-wave signal.", "Sit still while the headband warms up."
        rel = self._relative_power(sample)
        if rel is None:
            return None, "gray", "Waiting for a brain-wave signal.", "Check that the headband is on."
        # Drowsiness ratio from relative band power: (theta + alpha) / beta
        r = (rel["theta"] + rel["alpha"]) / max(rel["beta"], 1e-6)
        score = 100.0 / (1.0 + math.exp(1.15 * (r - 3.0)))
        score = _clip(score, 0.0, 100.0)
        if score >= 70:
            return score, "green", "You look awake and alert.", "Your brain looks alert. Good time for focused work."
        if score >= 45:
            return score, "yellow", "You may be starting to fade a little.", "A short stretch or a sip of water can help you reset."
        return score, "red", "Your brain looks sleepy right now.", "If you can, take a brief break or rest your eyes."

    def _attention_result(self, sample: Sample) -> Tuple[Optional[float], str, str]:
        if not sample.eeg_ok:
            return None, "steady", "Waiting for a signal"
        rel = self._relative_power(sample)
        if rel is None:
            return None, "steady", "Waiting for a signal"
        ei = rel["beta"] / max(rel["alpha"] + rel["theta"], 1e-6)
        score = _clip(100.0 * (1.0 - math.exp(-1.35 * ei)), 0.0, 100.0)
        self._ei_hist.append((sample.t, ei))
        now = sample.t
        recent = [v for t, v in self._ei_hist if now - t <= ATTENTION_WINDOW_S]
        older = [v for t, v in self._ei_hist if ATTENTION_WINDOW_S < now - t <= 2 * ATTENTION_WINDOW_S]
        if len(recent) < 5 or len(older) < 5:
            return score, "steady", "Still settling"
        rmean = sum(recent) / len(recent)
        omean = sum(older) / len(older)
        change = (rmean - omean) / max(abs(omean), 1e-6)
        if change > 0.10:
            return score, "rising", "Focus looks like it is building"
        if change < -0.10:
            return score, "dipping", "Focus looks like it is easing off"
        return score, "steady", "Focus looks steady"

    def _attention_tip(self, trend: str) -> str:
        if trend == "rising":
            return "This looks like a decent moment to start a task that needs your mind."
        if trend == "dipping":
            return "If your mind is wandering, try one slow breath and come back to one small step."
        return "Keep going at a comfortable pace. Small breaks still help."

    def _autonomic_result(self, now: float) -> Dict[str, Any]:
        remain = max(0.0, AUTONOMIC_NEED_S - self._hr_good_s)
        if remain > 0:
            mins = int(math.ceil(remain / 60.0))
            word = "minute" if mins == 1 else "minutes"
            return {
                "ready": False,
                "score": None,
                "progress": round(_clip(self._hr_good_s / AUTONOMIC_NEED_S, 0, 1), 3),
                "wait_message": f"Collecting data... {mins} more {word}",
                "meaning": "Your pulse needs a few quiet minutes before this card can lean calm or stressed.",
                "tip": "Keep a finger on the pulse sensor and stay fairly still.",
                "confidence": "Collecting",
                "agreement": None,
            }

        rmssd_vals = [v for t, v in self._rmssd_hist if now - t <= 180]
        temp_vals = [(t, v) for t, v in self._temp_hist if now - t <= 90]
        if len(rmssd_vals) < 8:
            return {
                "ready": False,
                "score": None,
                "progress": 0.92,
                "wait_message": "Collecting data... almost ready",
                "meaning": "Almost there - waiting on a clearer pulse pattern.",
                "tip": "Keep your finger gently on the sensor.",
                "confidence": "Collecting",
                "agreement": None,
            }

        rmssd = sum(rmssd_vals) / len(rmssd_vals)
        heart_calm = _clip((rmssd - 18.0) / 50.0, 0.0, 1.0)

        temp_calm = 0.5
        if len(temp_vals) >= 10:
            t0, v0 = temp_vals[0]
            t1, v1 = temp_vals[-1]
            dt_min = max((t1 - t0) / 60.0, 1e-3)
            slope = (v1 - v0) / dt_min
            temp_calm = _clip(0.5 + slope / 0.50, 0.0, 1.0)

        mix = 0.65 * heart_calm + 0.35 * temp_calm
        score = int(round(_clip(mix * 100.0, 0, 100)))
        heart_side = "calm" if heart_calm >= 0.55 else "stressed" if heart_calm <= 0.45 else "neutral"
        temp_side = "calm" if temp_calm >= 0.55 else "stressed" if temp_calm <= 0.45 else "neutral"
        agree = heart_side == temp_side and heart_side != "neutral"

        if score >= 62:
            meaning = "Your body looks more on the calm side."
            tip = "Nice. A slow breath can help you stay in this zone."
            lean = "calm"
        elif score <= 38:
            meaning = "Your body looks more on the stressed side."
            tip = "Try a few slow deep breaths."
            lean = "stressed"
        else:
            meaning = "Your body looks in the middle - not clearly calm or stressed."
            tip = "If you want to settle, lengthen your exhale for a minute."
            lean = "balanced"

        if agree:
            agreement = "Your pulse and skin temperature point the same way."
        elif heart_side == "neutral" or temp_side == "neutral":
            agreement = "One signal is clearer than the other, so this is a soft lean."
        else:
            agreement = "Your pulse and skin temperature do not fully agree, so confidence is lower."

        return {
            "ready": True,
            "score": score,
            "progress": 1.0,
            "lean": lean,
            "meaning": meaning,
            "tip": tip,
            "agreement": agreement,
            "wait_message": None,
            "confidence": "Moderate" if agree else "Low to moderate",
        }

    def _quality(self, sample: Sample, moving: bool, eeg_bad: bool, as_poor: bool) -> Tuple[str, Optional[str], Optional[str]]:
        motion_warning = "Please stay still" if moving else None
        if as_poor or (eeg_bad and not sample.eeg_warming):
            msg = "Low confidence: check electrode contact"
            return "Low", msg, motion_warning
        if sample.eeg_warming:
            return "Low", "Brain-wave sensor is warming up.", motion_warning
        if moving:
            return "Low", "Movement makes these readings less trustworthy.", motion_warning
        if self._calibrated and (self._alpha_suppression or 0) >= 20:
            return "Good", None, None
        if not self._calibrated:
            return "Moderate", "Run the short check for a more trustworthy reading.", None
        return "Moderate", None, None

    def _waveforms(self, sample: Sample) -> Tuple[List[float], List[float]]:
        n = 128
        eeg = []
        self._wave_phase += 0.35
        for i in range(n):
            t = i / 250.0
            v = 0.0
            for name, scale in (("delta", 1.0), ("theta", 0.85), ("alpha", 0.7), ("beta", 0.45), ("gamma", 0.2)):
                f = float(sample.band_hz.get(name, 0.0) or 0.0)
                a = float(sample.band_uv.get(name, 0.0) or 0.0)
                if f <= 0:
                    f = {"delta": 2.0, "theta": 6.0, "alpha": 10.0, "beta": 20.0, "gamma": 38.0}[name]
                v += a * math.sin(2 * math.pi * f * t + self._wave_phase * (0.4 + 0.15 * scale))
            eeg.append(round(v, 3))
        mx = max((abs(x) for x in eeg), default=1.0) or 1.0
        eeg = [x / mx for x in eeg]

        hr = sample.hr or 70.0
        bpm = _clip(hr, 40.0, 140.0)
        self._ppg_phase += (bpm / 60.0) * 0.12
        ppg = []
        for i in range(n):
            x = (i / n + self._ppg_phase) % 1.0
            # Simple pulse shape for display only
            peak = math.exp(-((x - 0.18) ** 2) / 0.004) + 0.35 * math.exp(-((x - 0.32) ** 2) / 0.008)
            ppg.append(round(peak, 4))
        if not sample.finger:
            ppg = [0.08 * math.sin(i / 6.0) for i in range(n)]
        return eeg, ppg
