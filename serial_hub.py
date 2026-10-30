"""USB serial reader with auto-reconnect."""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

import serial
from serial.tools import list_ports

from parser import SerialParser
from analysis import Sample


LIKELY = ("ch340", "ch910", "cp210", "silicon labs", "usb serial", "uart", "espressif", "usb-serial")


def list_com_ports() -> List[dict]:
    out = []
    for p in list_ports.comports():
        desc = p.description or ""
        hwid = p.hwid or ""
        blob = f"{desc} {hwid} {p.device}".lower()
        likely = any(k in blob for k in LIKELY)
        out.append(
            {
                "device": p.device,
                "name": f"{p.device} - {desc}" if desc else p.device,
                "likely": likely,
            }
        )
    out.sort(key=lambda x: (not x["likely"], x["device"]))
    return out


class SerialHub:
    def __init__(self, on_sample: Callable[[Sample], None], on_status: Callable[[dict], None]) -> None:
        self.on_sample = on_sample
        self.on_status = on_status
        self._lock = threading.Lock()
        self._port: Optional[str] = None
        self._ser: Optional[serial.Serial] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._parser = SerialParser()
        self.connected = False
        self.last_error: Optional[str] = None
        self.reconnect_tries = 0

    def connect(self, port: str) -> None:
        self.disconnect()
        self._stop.clear()
        self._port = port
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._close()
        self.connected = False
        self._port = None
        self.on_status(self.status("Disconnected"))

    def status(self, message: str) -> dict:
        return {
            "connected": self.connected,
            "port": self._port,
            "message": message,
            "error": self.last_error,
            "reconnect_tries": self.reconnect_tries,
        }

    def _close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _open(self) -> bool:
        assert self._port
        try:
            self._ser = serial.Serial(self._port, 115200, timeout=0.4)
            time.sleep(0.2)
            self._ser.reset_input_buffer()
            self.connected = True
            self.last_error = None
            self.reconnect_tries = 0
            self._parser = SerialParser()
            self.on_status(self.status(f"Connected to {self._port}"))
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = f"Could not open {self._port}. {exc}"
            self.on_status(self.status(self.last_error))
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._ser is None or not self._ser.is_open:
                if not self._open():
                    self.reconnect_tries += 1
                    wait = min(8.0, 1.2 * self.reconnect_tries)
                    self.on_status(
                        {
                            **self.status(
                                f"Board unplugged or busy. Trying again in {wait:.0f}s..."
                            ),
                            "error": self.last_error
                            or "The board disconnected. Trying to reconnect.",
                        }
                    )
                    self._stop.wait(wait)
                    continue
            try:
                raw = self._ser.readline()
            except Exception as exc:
                self.connected = False
                self.last_error = "The board disconnected. Trying to reconnect."
                self._close()
                self.on_status(self.status(self.last_error + f" ({exc})"))
                continue
            if not raw:
                continue
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            sample = self._parser.push_line(line)
            if sample is not None:
                self.on_sample(sample)
