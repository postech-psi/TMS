from pathlib import Path
from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import butter, filtfilt

# ===== CONFIGURATION =====
YEAR = "2026"
DATE_FOLDER = "4_2"
INPUT_FILENAME = "26.04.03 data.TXT"
DRIFT_FILENAME = "loadcell_drift.TXT"
LOADCELL_CHANNEL_INDEX = 0
BAROMETER_CHANNEL_INDEX = 1
SKIP_INITIAL_LINES = 2
SAMPLING_RATE = 320

# Load cell calibration
CALIBRATION_SLOPE = -0.0391
CALIBRATION_INTERCEPT = -193.0049
GRAVITATIONAL_CONSTANT = 9.80665
FORCE_OFFSET = 0.0

# Experimental drift correction
DRIFT_MODE = "exponential"  # "off", "horizontal", or "exponential"
INPUT_TIME_GAP_SECONDS = 0.0

# Signal filtering
LOADCELL_LOWPASS_CUTOFF_HZ = 25.0
LOADCELL_LOWPASS_ORDER = 2
BAROMETER_LOWPASS_CUTOFF_HZ = 3.0
BAROMETER_LOWPASS_ORDER = 2
PRESSURE_BASELINE_WINDOW_SECONDS = 0.5

# Pressure conversion
PRESSURE_SLOPE = 0.0027
PRESSURE_INTERCEPT = -0.11
PRESSURE_LABEL = "Gauge Pressure"

# Analysis
PROPELLANT_MASS = None
THRUST_EVENT_THRESHOLD_RATIO = 0.03

# Outputs
GENERATE_PLOTS = True
SAVE_PLOT = True
SAVE_REPORT = True
SAVE_DATA = True
OUTPUT_FOLDER_NAME = "analysis"

# Plot palette
FORCE_RAW_COLOR = "#B8B8B8"
FORCE_FILTERED_COLOR = "#4C6472"
FORCE_PEAK_COLOR = "#4F86C6"
# =========================

FORCE_CORRECTED_LABEL = "Unfiltered corrected force"
FORCE_FILTERED_LABEL = "Filtered corrected force"
FORCE_PEAK_LABEL = "Peak force"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER
INPUT_FILE = DATA_DIR / INPUT_FILENAME
DRIFT_FILE = DATA_DIR / DRIFT_FILENAME
OUTPUT_DIR = DATA_DIR / OUTPUT_FOLDER_NAME
INTERLEAVED_CHANNEL_COUNT = 2


def load_single_channel_values(file_path: str | Path) -> np.ndarray:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as file:
        values = [float(line.strip()) for line in file if line.strip()]
    return np.array(values, dtype=float)


def load_interleaved_channel(file_path: str | Path, channel_index: int) -> np.ndarray:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]
    values = [float(lines[i]) for i in range(channel_index, len(lines), INTERLEAVED_CHANNEL_COUNT)]
    return np.array(values, dtype=float)[SKIP_INITIAL_LINES:]


def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def convert_to_pressure(raw_values: np.ndarray) -> np.ndarray:
    return PRESSURE_SLOPE * raw_values + PRESSURE_INTERCEPT


def zero_phase_lowpass(values: np.ndarray, cutoff_hz: float, order: int) -> np.ndarray:
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


def r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1.0 - (ss_res / ss_tot)


def exponential_model(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    return a * np.exp(b * x) + c


def fit_exponential_drift(time: np.ndarray, force: np.ndarray) -> dict[str, object]:
    initial_guess = (force[0] - force[-1], -1.0, force[-1])
    params, _ = curve_fit(exponential_model, time, force, p0=initial_guess, maxfev=20000)
    fitted = exponential_model(time, *params)
    return {"params": params, "r2": r_squared(force, fitted)}


def find_event_bounds(signal: np.ndarray, threshold_ratio: float) -> dict[str, float | int]:
    peak_value = float(np.max(signal))
    peak_idx = int(np.argmax(signal))
    threshold_value = threshold_ratio * peak_value
    above_threshold = signal >= threshold_value
    if np.any(above_threshold):
        start_idx = int(np.where(above_threshold)[0][0])
        end_idx = int(np.where(above_threshold)[0][-1])
    else:
        start_idx = 0
        end_idx = len(signal) - 1
    return {
        "peak_value": peak_value,
        "peak_idx": peak_idx,
        "threshold_value": threshold_value,
        "start_idx": start_idx,
        "end_idx": end_idx,
    }


def calculate_horizontal_offset(raw_force: np.ndarray) -> float:
    filtered_force = zero_phase_lowpass(raw_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    seed_count = max(5, min(filtered_force.size, int(0.5 * SAMPLING_RATE)))
    baseline_seed = float(np.mean(filtered_force[:seed_count]))
    peak_force = float(np.max(filtered_force))
    trigger_force = baseline_seed + THRUST_EVENT_THRESHOLD_RATIO * (peak_force - baseline_seed)
    ignition_candidates = np.where(filtered_force >= trigger_force)[0]
    ignition_idx = int(ignition_candidates[0]) if ignition_candidates.size else filtered_force.size - 1
    averaging_end_idx = max(1, ignition_idx // 2)
    return float(np.mean(raw_force[:averaging_end_idx]))


def apply_drift_correction(time: np.ndarray, raw_force: np.ndarray, drift_force: Optional[np.ndarray]) -> dict[str, object]:
    if DRIFT_MODE == "off":
        return {
            "label": "Off",
            "modeled_drift": np.zeros_like(raw_force),
            "corrected_force": raw_force.copy(),
        }
    if DRIFT_MODE == "horizontal":
        offset_force = calculate_horizontal_offset(raw_force)
        return {
            "label": "Horizontal offset",
            "modeled_drift": np.full_like(raw_force, offset_force, dtype=float),
            "corrected_force": raw_force - offset_force,
        }
    if drift_force is None or drift_force.size == 0:
        raise ValueError("Drift reference data is required for exponential drift correction mode.")
    drift_time = np.arange(drift_force.size) / SAMPLING_RATE
    fit_result = fit_exponential_drift(drift_time, drift_force)
    effective_time = time + INPUT_TIME_GAP_SECONDS
    modeled_drift = exponential_model(effective_time, *np.asarray(fit_result["params"]))
    return {
        "label": "Exponential",
        "modeled_drift": modeled_drift,
        "corrected_force": raw_force - modeled_drift,
        "r2": float(fit_result["r2"]),
    }


def calculate_pressure_baseline(pressure_values: np.ndarray) -> float:
    if pressure_values.size == 0:
        return 0.0
    baseline_count = max(5, min(pressure_values.size, int(PRESSURE_BASELINE_WINDOW_SECONDS * SAMPLING_RATE)))
    return float(np.mean(pressure_values[:baseline_count]))


def calculate_pressure_metrics(time: np.ndarray, filtered_gauge_pressure: np.ndarray) -> Dict[str, float]:
    event = find_event_bounds(filtered_gauge_pressure, THRUST_EVENT_THRESHOLD_RATIO)
    peak_idx = int(event["peak_idx"])
    return {
        "peak_pressure": float(event["peak_value"]),
        "peak_pressure_time": float(time[peak_idx]),
        "pressure_rise_time": float(time[int(event["start_idx"])]),
    }


def calculate_thrust_metrics(
    time: np.ndarray,
    filtered_force: np.ndarray,
    pressure_rise_time: Optional[float] = None,
    propellant_mass: Optional[float] = None,
) -> Dict[str, object]:
    dt = time[1] - time[0] if len(time) > 1 else 1.0 / SAMPLING_RATE
    event = find_event_bounds(filtered_force, THRUST_EVENT_THRESHOLD_RATIO)
    ignition_idx = int(event["start_idx"])
    burnout_idx = int(event["end_idx"])
    ignition_time = float(time[ignition_idx])
    burnout_time = float(time[burnout_idx])
    burn_time = burnout_time - ignition_time
    total_impulse = float(np.trapezoid(filtered_force[ignition_idx:burnout_idx + 1], dx=dt))
    avg_thrust = total_impulse / burn_time if burn_time > 0 else 0.0
    specific_impulse = None
    if propellant_mass is not None and propellant_mass > 0:
        specific_impulse = total_impulse / (propellant_mass * GRAVITATIONAL_CONSTANT)
    pressure_to_force_delay = ignition_time - pressure_rise_time if pressure_rise_time is not None else None
    return {
        "peak_thrust": float(event["peak_value"]),
        "peak_time": float(time[int(event["peak_idx"])]),
        "ignition_time": ignition_time,
        "burnout_time": burnout_time,
        "burn_time": burn_time,
        "ignition_delay": ignition_time,
        "pressure_to_force_delay": max(0.0, pressure_to_force_delay) if pressure_to_force_delay is not None else None,
        "total_impulse": total_impulse,
        "avg_thrust": avg_thrust,
        "specific_impulse": specific_impulse,
    }


def get_output_path(suffix: str) -> Path:
    return OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_{suffix}"


def save_current_figure(filename: str) -> None:
    if not SAVE_PLOT:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(get_output_path(filename), dpi=300, bbox_inches="tight", facecolor="white")


def main() -> None:
    loadcell_adc = load_interleaved_channel(INPUT_FILE, LOADCELL_CHANNEL_INDEX)
    barometer_raw = load_interleaved_channel(INPUT_FILE, BAROMETER_CHANNEL_INDEX)
    drift_adc = load_single_channel_values(DRIFT_FILE) if DRIFT_MODE == "exponential" else np.array([], dtype=float)
    time = np.arange(loadcell_adc.size) / SAMPLING_RATE

    raw_force = calibrated_force(loadcell_adc)
    raw_pressure = convert_to_pressure(barometer_raw)
    drift_force = calibrated_force(drift_adc) if drift_adc.size else None

    drift_result = apply_drift_correction(time, raw_force, drift_force)
    corrected_force = np.asarray(drift_result["corrected_force"], dtype=float)
    filtered_force = zero_phase_lowpass(corrected_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    filtered_pressure = zero_phase_lowpass(raw_pressure, BAROMETER_LOWPASS_CUTOFF_HZ, BAROMETER_LOWPASS_ORDER)
    pressure_baseline = calculate_pressure_baseline(filtered_pressure)
    raw_gauge_pressure = raw_pressure - pressure_baseline
    filtered_gauge_pressure = filtered_pressure - pressure_baseline

    pressure_metrics = calculate_pressure_metrics(time, filtered_gauge_pressure)
    thrust_metrics = calculate_thrust_metrics(time, filtered_force, pressure_metrics["pressure_rise_time"], PROPELLANT_MASS)

    if GENERATE_PLOTS:
        fig, ax = plt.subplots(figsize=(13, 6.5))
        ax.plot(time, corrected_force, color=FORCE_RAW_COLOR, linewidth=0.9, alpha=0.75, label=FORCE_CORRECTED_LABEL)
        ax.plot(time, filtered_force, color=FORCE_FILTERED_COLOR, linewidth=2.1, label=FORCE_FILTERED_LABEL)
        ax.plot(thrust_metrics["peak_time"], thrust_metrics["peak_thrust"], "o", color=FORCE_PEAK_COLOR, markersize=4.0, label=FORCE_PEAK_LABEL)
        ax.set_title(f"Experimental Drift Plot - {INPUT_FILENAME}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Force (N)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        plt.tight_layout()
        save_current_figure("experimental_force_plot.png")
        plt.show()

    print("Experimental run complete")
    print(f"Drift mode: {drift_result['label']}")
    print(f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N")
    print(f"Peak pressure: {pressure_metrics['peak_pressure']:.3f}")


if __name__ == "__main__":
    main()
