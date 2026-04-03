from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt

# ===== CONFIGURATION =====
YEAR = "2026"
DATE_FOLDER = "4_2"
INPUT_FILENAME = "/temp/dynamic.TXT"
SAMPLING_RATE = 320
# !!로드셀 켈리브레이션 코드의 경우 full 로 설정!!
LINE_MODE = "full"  # "full", "odd", or "even" 
SKIP_INITIAL_LINES = 2

# Load cell calibration
CALIBRATION_SLOPE = -0.0391
CALIBRATION_INTERCEPT = -193.0049
GRAVITATIONAL_CONSTANT = 9.80665
FORCE_OFFSET = 0.0

# Filtering
LOADCELL_LOWPASS_CUTOFF_HZ = 5
LOADCELL_LOWPASS_ORDER = 2
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER 
INPUT_FILE = DATA_DIR / INPUT_FILENAME


def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    """Convert loadcell ADC values to force in Newtons."""
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def zero_phase_lowpass(values: np.ndarray, cutoff_hz: float, order: int) -> np.ndarray:
    """Apply a zero-phase Butterworth low-pass filter."""
    if values.size < 3:
        return values.copy()
    nyquist_hz = 0.5 * SAMPLING_RATE
    if cutoff_hz <= 0 or cutoff_hz >= nyquist_hz:
        raise ValueError(f"cutoff_hz must be between 0 and {nyquist_hz:.2f} Hz")
    b, a = butter(order, cutoff_hz / nyquist_hz, btype="low")
    padlen = 3 * (max(len(a), len(b)) - 1)
    if values.size <= padlen:
        return values.copy()
    return filtfilt(b, a, values)


def load_single_channel_values(file_path: str | Path, line_mode: str = "full") -> np.ndarray:
    """Load numeric lines from a single-channel loadcell file."""
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]

    values = np.array([float(line) for line in lines], dtype=float)
    values = values[SKIP_INITIAL_LINES:]

    if line_mode == "odd":
        selected_values = values[0::2]
    elif line_mode == "even":
        selected_values = values[1::2]
    elif line_mode == "full":
        selected_values = values
    else:
        raise ValueError("LINE_MODE must be 'full', 'odd', or 'even'.")

    return np.array(selected_values, dtype=float)


def main() -> None:
    loadcell_adc = load_single_channel_values(INPUT_FILE, LINE_MODE)
    time = np.arange(loadcell_adc.size) / SAMPLING_RATE
    raw_force = calibrated_force(loadcell_adc)
    filtered_force = zero_phase_lowpass(raw_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(time, raw_force, color="#9A9A9A", linewidth=0.8, alpha=0.85, label="Raw loadcell")
    ax.plot(time, filtered_force, color="#1F5BD8", linewidth=2.0, label="Filtered loadcell")
    ax.set_title(f"Loadcell Raw vs Filtered - {INPUT_FILENAME} ({LINE_MODE})")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
