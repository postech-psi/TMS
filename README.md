# Thrust Measurement System (TMS)

The Thrust Measurement System (TMS) is a deterministic, embedded data acquisition unit engineered for high‑fidelity propulsion analysis during static‑fire testing. Built on the Arduino Nano platform, it runs an interrupt‑driven control loop that synchronizes ignition with high‑speed sensor acquisition. Dual 16‑bit ADS1115 ADCs capture at 320 samples per second (SPS), while a finite‑state machine manages automated file journaling, failsafe relays, and timing to preserve data integrity throughout the 15‑second test window.

## What's in this repo
- `TMS Unit/` — Arduino sketches (`.ino`) and a Python sampling‑rate checker.
- `Calibration/` — Python tools for load‑cell calibration (`calibration.py`), raw‑to‑force conversion (`tms_data__calibrated.py`), and full analysis/plots (`tms_update.py`).
- `Data/` — Sample raw logs and analysis outputs.

## Quick start (Python tools)
1. Install Python 3.10+ and create an env:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Calibrate a load cell:
   - Set `data_dir` and `weights_file` in `Calibration/calibration.py` to your dataset.
   - Run `python Calibration/calibration.py` to print slope/intercept and show the calibration plot.
3. Convert raw data to Newtons:
   ```bash
   python Calibration/tms_data__calibrated.py
   ```
   Updates go to `Data/11_27/calibrated_loadcell_test.txt` by default.
4. Full thrust analysis & plots:
   - Adjust `INPUT_FILE`, calibration coefficients, and options in `Calibration/tms_update.py`.
   - Run `python Calibration/tms_update.py` to generate metrics (peak thrust, impulse, motor class) and save plots in `Data/analysis_output/`.

> Note: Some scripts currently reference absolute paths; set them to your local paths if running on another machine.

## License
MIT License. See `LICENSE` for details.
