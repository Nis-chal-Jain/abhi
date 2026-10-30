# Biosignal live dashboard

A real-time dashboard for the ESP32 bio-signal monitor (pulse, brain-wave bands, motion, skin temperature). Scoring runs on this computer in Python. The browser only shows results.

Your ESP32 sketch is not modified. Leave it running at **115200 baud** as it already does.

## Start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) if needed, and tick **Add python.exe to PATH**.
2. Double-click `start.bat`.
3. A browser tab opens in **Demo Mode** so you can try the layout without hardware.
4. To use the board: turn **Demo Mode** off, pick the COM port, click **Connect**.

The app is at [http://127.0.0.1:8765](http://127.0.0.1:8765). Close the black window to stop it.

## What you will see

- Live heart rate, brain-wave band levels, skin temperature, and small pulse / brain / motion traces
- Four result cards: Vigilance / Drowsiness, Attention / Focus, Mood Lean, Autonomic Balance
- A session history graph
- Calibration: 30 seconds eyes closed, then 30 seconds eyes open
- Record session and Export CSV (raw sensor values plus final labels - not working notes)

## Hardware notes

- Pulse sensor: keep a finger gently on the MAX30102.
- Autonomic Balance needs a few quiet minutes of pulse data before it fills in.
- Mood Lean needs **two** forehead electrodes (left and right). The current ESP32 sketch sends **one** analog brain-wave channel, so that card stays unavailable until the hardware can send both.
- Move as little as you can while a reading is taken. Motion is flagged as unreliable.

## Troubleshooting

- **No COM ports**: install the CP2102 or CH340 USB driver for your ESP32 board, then click the refresh control.
- **Board disconnected**: leave the page open; the app retries on its own.
- **Python not found**: reinstall Python with PATH enabled, then run `start.bat` again.

Trend indicators are for information only, not medical diagnoses.
