from pathlib import Path
from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import butter, filtfilt

# ===== CONFIGURATION =====
YEAR = "2026"
DATE_FOLDER = "4_2"
INPUT_FILENAME = "TMS_4_12.TXT"
DRIFT_FILENAME = "loadcell_drift.TXT"
LOADCELL_LINE_START = 0
BAROMETER_LINE_START = 1
SAMPLING_RATE = 320

# Load cell calibration
CALIBRATION_SLOPE = -0.0391
CALIBRATION_INTERCEPT = -193.0049
CALIBRATION_R_SQUARED = 0.999948
GRAVITATIONAL_CONSTANT = 9.80665
FORCE_OFFSET = 0.0

# Drift and signal filtering
DRIFT_MODE = "exponential"  # "off", "horizontal", or "exponential"
LOADCELL_LOWPASS_CUTOFF_HZ = 15.0
LOADCELL_LOWPASS_ORDER = 2
BAROMETER_LOWPASS_CUTOFF_HZ = 3.0
BAROMETER_LOWPASS_ORDER = 2

# Pressure conversion
PRESSURE_SLOPE = 0.0027
PRESSURE_INTERCEPT = -0.11
PRESSURE_LABEL = "Gauge Pressure"

# Analysis
PROPELLANT_MASS = None
THRUST_EVENT_THRESHOLD_RATIO = 0.03

GENERATE_PLOTS = True
SAVE_PLOT = True
SAVE_REPORT = True
SAVE_DATA = True
OUTPUT_FOLDER_NAME = "analysis"
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER
INPUT_FILE = DATA_DIR / INPUT_FILENAME
DRIFT_FILE = DATA_DIR / DRIFT_FILENAME
OUTPUT_DIR = DATA_DIR / OUTPUT_FOLDER_NAME
REPORT_RULE = "=" * 72
SECTION_RULE = "-" * 72


def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    """Convert loadcell ADC values to force in Newtons."""
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def convert_to_pressure(raw_values: np.ndarray) -> np.ndarray:
    """Convert barometer channel values to pressure using the provided linear calibration."""
    return PRESSURE_SLOPE * raw_values + PRESSURE_INTERCEPT


def load_single_channel_values(file_path: str | Path) -> np.ndarray:
    """Load every numeric line from a single-channel test file."""
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as file:
        values = [float(line.strip()) for line in file if line.strip()]
    return np.array(values, dtype=float)


def load_interleaved_channel(file_path: str | Path, line_start: int) -> np.ndarray:
    """Load one channel from an interleaved TMS text file."""
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as file:
        lines = file.readlines()
    values = [
        float(lines[i].strip())
        for i in range(line_start, len(lines), 2)
        if lines[i].strip()
    ]
    return np.array(values, dtype=float)


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


def exponential_model(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Exponential drift model."""
    return a * np.exp(b * x) + c


def fit_exponential_drift(time: np.ndarray, force: np.ndarray) -> dict[str, object]:
    """Fit an exponential drift model to the drift-reference loadcell data."""
    initial_guess = (force[0] - force[-1], -1.0, force[-1])
    params, _ = curve_fit(
        exponential_model,
        time,
        force,
        p0=initial_guess,
        maxfev=20000,
    )
    fitted = exponential_model(time, *params)
    return {
        "params": params,
        "y_fit": fitted,
        "r2": r_squared(force, fitted),
    }


def estimate_idle_force(raw_force: np.ndarray) -> dict[str, float]:
    """Estimate the idle-state mean from the pre-ignition portion of the test data."""
    filtered_raw_force = zero_phase_lowpass(raw_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    seed_count = max(5, min(filtered_raw_force.size, int(0.5 * SAMPLING_RATE)))
    baseline_seed = float(np.mean(filtered_raw_force[:seed_count]))
    peak_force = float(np.max(filtered_raw_force))
    trigger_force = baseline_seed + THRUST_EVENT_THRESHOLD_RATIO * (peak_force - baseline_seed)
    ignition_candidates = np.where(filtered_raw_force >= trigger_force)[0]
    ignition_idx = int(ignition_candidates[0]) if ignition_candidates.size else filtered_raw_force.size
    idle_end_idx = max(seed_count, ignition_idx)
    idle_mean = float(np.mean(filtered_raw_force[:idle_end_idx]))
    return {
        "idle_mean": idle_mean,
        "idle_end_idx": float(idle_end_idx),
        "trigger_force": trigger_force,
    }


def build_drift_result(mode: str, time: np.ndarray, raw_force: np.ndarray, drift_force: Optional[np.ndarray]) -> dict[str, object]:
    """Apply the selected drift correction model and return correction metadata."""
    if mode == "off":
        modeled_drift = np.zeros_like(raw_force)
        return {
            "mode": mode,
            "label": "Off",
            "description": "No drift correction applied.",
            "modeled_drift": modeled_drift,
            "corrected_force": raw_force.copy(),
            "r2": None,
            "params": None,
        }
    if mode == "horizontal":
        idle_result = estimate_idle_force(raw_force)
        idle_force = idle_result["idle_mean"]
        modeled_drift = np.full_like(raw_force, idle_force, dtype=float)
        return {
            "mode": mode,
            "label": "Horizontal offset",
            "description": (
                f"Constant idle-state offset from test data mean before ignition: {idle_force:.6f} N "
                f"(first {int(idle_result['idle_end_idx'])} samples)"
            ),
            "modeled_drift": modeled_drift,
            "corrected_force": raw_force - modeled_drift,
            "r2": None,
            "params": None,
        }
    if mode == "exponential":
        if drift_force is None or drift_force.size == 0:
            raise ValueError("Drift reference data is required for exponential drift correction mode.")
        drift_time = np.arange(drift_force.size) / SAMPLING_RATE
        fit_result = fit_exponential_drift(drift_time, drift_force)
        modeled_drift = exponential_model(time, *np.asarray(fit_result["params"]))
        return {
            "mode": mode,
            "label": "Exponential",
            "description": format_drift_formula(np.asarray(fit_result["params"])),
            "modeled_drift": modeled_drift,
            "corrected_force": raw_force - modeled_drift,
            "r2": float(fit_result["r2"]),
            "params": np.asarray(fit_result["params"]),
        }
    raise ValueError(f"Unsupported DRIFT_MODE: {mode}. Use 'off', 'horizontal', or 'exponential'.")


def r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Return coefficient of determination for one fitted curve."""
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1.0 - (ss_res / ss_tot)


def calculate_thrust_metrics(
    time: np.ndarray,
    thrust_filtered: np.ndarray,
    propellant_mass: Optional[float] = None,
) -> Dict[str, object]:
    """Calculate executive thrust metrics from the filtered corrected force."""
    dt = time[1] - time[0] if len(time) > 1 else 1.0 / SAMPLING_RATE
    peak_thrust = float(np.max(thrust_filtered))
    peak_idx = int(np.argmax(thrust_filtered))
    peak_time = float(time[peak_idx])
    threshold_force = THRUST_EVENT_THRESHOLD_RATIO * peak_thrust
    above_threshold = thrust_filtered >= threshold_force
    if np.any(above_threshold):
        ignition_idx = int(np.where(above_threshold)[0][0])
        burnout_idx = int(np.where(above_threshold)[0][-1])
    else:
        ignition_idx = 0
        burnout_idx = len(thrust_filtered) - 1
    ignition_time = float(time[ignition_idx])
    burnout_time = float(time[burnout_idx])
    burn_time = burnout_time - ignition_time
    total_impulse = float(np.trapezoid(thrust_filtered[ignition_idx:burnout_idx + 1], dx=dt))
    avg_thrust = total_impulse / burn_time if burn_time > 0 else 0.0
    if propellant_mass is not None and propellant_mass > 0:
        specific_impulse = total_impulse / (propellant_mass * GRAVITATIONAL_CONSTANT)
    else:
        specific_impulse = None
    return {
        "peak_thrust": peak_thrust,
        "peak_time": peak_time,
        "peak_idx": peak_idx,
        "ignition_idx": ignition_idx,
        "ignition_time": ignition_time,
        "burnout_idx": burnout_idx,
        "burnout_time": burnout_time,
        "burn_time": burn_time,
        "ignition_delay": ignition_time,
        "total_impulse": total_impulse,
        "avg_thrust": avg_thrust,
        "specific_impulse": specific_impulse,
        "threshold_force": threshold_force,
    }


def calculate_pressure_metrics(time: np.ndarray, pressure_filtered_offset: np.ndarray) -> Dict[str, float]:
    """Calculate simple executive pressure metrics from the filtered offset pressure."""
    peak_idx = int(np.argmax(pressure_filtered_offset))
    return {
        "peak_pressure": float(np.max(pressure_filtered_offset)),
        "peak_pressure_time": float(time[peak_idx]),
        "pressure_span": float(np.max(pressure_filtered_offset) - np.min(pressure_filtered_offset)),
        "pressure_mean": float(np.mean(pressure_filtered_offset)),
        "pressure_std": float(np.std(pressure_filtered_offset)),
    }


def format_drift_formula(params: np.ndarray) -> str:
    """Return a compact human-readable drift formula."""
    return f"y = {params[0]:.6f} * exp({params[1]:.6f} * t) + {params[2]:.6f}"


def write_report_section(file, title: str, lines: list[str]) -> None:
    """Write one report section with consistent formatting."""
    file.write(f"{SECTION_RULE}\n")
    file.write(f"{title}\n")
    file.write(f"{SECTION_RULE}\n")
    file.write("\n".join(lines))
    file.write("\n\n")


def format_project_relative_path(path: str | Path) -> str:
    """Return a report-friendly path rooted at the project folder name."""
    path = Path(path).resolve()
    try:
        relative_path = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return str(path)
    return str(Path(PROJECT_ROOT.name) / relative_path)


def append_report_content(
    file,
    thrust_metrics: Dict[str, object],
    pressure_metrics: Dict[str, float],
    drift_result: dict[str, object],
    pressure_baseline: float,
) -> None:
    """Write the executive report content into an already-open text file."""
    threshold_percent = int(THRUST_EVENT_THRESHOLD_RATIO * 100)

    file.write(f"{REPORT_RULE}\n")
    file.write("STATIC FIRE REPORT\n")
    file.write(f"{REPORT_RULE}\n\n")
    file.write(f"Input file: {format_project_relative_path(INPUT_FILE)}\n")
    file.write(f"Drift reference: {format_project_relative_path(DRIFT_FILE)}\n")
    file.write(f"Sampling rate: {SAMPLING_RATE} sps\n\n")

    thrust_lines = [
        f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms",
        f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s",
        f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N",
        f"Average thrust: {thrust_metrics['avg_thrust']:.2f} N",
        f"{threshold_percent} percent threshold: {thrust_metrics['threshold_force']:.2f} N",
        f"Ignition time: {thrust_metrics['ignition_time'] * 1000:.1f} ms",
        f"Burn end: {thrust_metrics['burnout_time'] * 1000:.1f} ms",
        f"Burn time: {thrust_metrics['burn_time'] * 1000:.1f} ms",
        f"Loadcell filter: Butterworth low-pass {LOADCELL_LOWPASS_CUTOFF_HZ:.1f} Hz, order {LOADCELL_LOWPASS_ORDER}",
    ]
    if thrust_metrics["specific_impulse"] is not None:
        thrust_lines.insert(4, f"Specific impulse: {thrust_metrics['specific_impulse']:.1f} s")
    write_report_section(file, "LOADCELL / THRUST SUMMARY", thrust_lines)

    write_report_section(
        file,
        "DRIFT MODEL",
        [
            f"Mode: {drift_result['label']}",
            f"Details: {drift_result['description']}",
            *([f"Fit R^2: {drift_result['r2']:.6f}"] if drift_result["r2"] is not None else []),
        ],
    )

    write_report_section(
        file,
        "BAROMETER / PRESSURE SUMMARY",
        [
            f"Pressure conversion: y = {PRESSURE_SLOPE}x {PRESSURE_INTERCEPT:+.2f}",
            f"Gauge baseline removed: {pressure_baseline:.6f}",
            f"Peak pressure: {pressure_metrics['peak_pressure']:.3f} at {pressure_metrics['peak_pressure_time']:.3f} s",
            f"Pressure span: {pressure_metrics['pressure_span']:.3f}",
            f"Pressure std: {pressure_metrics['pressure_std']:.3f}",
            f"Pressure filter: Butterworth low-pass {BAROMETER_LOWPASS_CUTOFF_HZ:.1f} Hz, order {BAROMETER_LOWPASS_ORDER}",
        ],
    )

    write_report_section(
        file,
        "CALIBRATION TRACEABILITY",
        [
            f"Calibration slope: {CALIBRATION_SLOPE:.6f} kg/ADC",
            f"Calibration intercept: {CALIBRATION_INTERCEPT:.4f} kg",
            f"Calibration R^2: {CALIBRATION_R_SQUARED:.6f}",
        ],
    )
    file.write(f"{REPORT_RULE}\n")


def build_console_summary_lines(
    thrust_metrics: Dict[str, object],
    pressure_metrics: Dict[str, float],
    drift_result: dict[str, object],
) -> list[str]:
    """Return a compact console summary for the processed run."""
    return [
        f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N",
        f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s",
        f"Ignition time: {thrust_metrics['ignition_time'] * 1000:.1f} ms",
        f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms",
        f"Burn time: {thrust_metrics['burn_time'] * 1000:.1f} ms",
        f"Peak pressure: {pressure_metrics['peak_pressure']:.3f}",
        f"Drift mode: {drift_result['label']}",
    ]


def print_terminal_summary(
    thrust_metrics: Dict[str, object],
    pressure_metrics: Dict[str, float],
    drift_result: dict[str, object],
    loadcell_samples: int,
    barometer_samples: int,
    drift_samples: int,
) -> None:
    """Print only the essential run information to the terminal."""
    print("Run complete")
    print(f"Samples used: loadcell={loadcell_samples}, barometer={barometer_samples}, drift={drift_samples}")
    for line in build_console_summary_lines(thrust_metrics, pressure_metrics, drift_result):
        print(line)
    print(f"Output folder: {format_project_relative_path(OUTPUT_DIR)}")


def plot_loadcell_summary(
    time: np.ndarray,
    raw_force: np.ndarray,
    corrected_force: np.ndarray,
    filtered_force: np.ndarray,
    thrust_metrics: Dict[str, object],
) -> None:
    """Create a dedicated loadcell/thrust figure."""
    fig, ax = plt.subplots(figsize=(13, 6.5))
    plot_end_time = min(time[-1], thrust_metrics["burnout_time"] + max(0.2, 0.25 * thrust_metrics["burn_time"]))

    ax.plot(time, raw_force, color="#9A9A9A", linewidth=0.8, alpha=0.85, label="Raw calibrated force")
    ax.plot(time, corrected_force, color="#E07A2D", linewidth=0.9, alpha=0.8, label="Drift-corrected force")
    ax.plot(
        time,
        filtered_force,
        color="#1F5BD8",
        linewidth=2.0,
        label="Filtered thrust",
    )
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.4)

    threshold_force = thrust_metrics["threshold_force"]
    ax.axvspan(0, thrust_metrics["ignition_time"], color="#F9EDEE", alpha=0.9, lw=0)
    ax.axvspan(thrust_metrics["ignition_time"], thrust_metrics["burnout_time"], color="#EDF7F0", alpha=0.95, lw=0)
    ax.axvspan(thrust_metrics["burnout_time"], time[-1], color="#F1F2FB", alpha=0.95, lw=0)
    ax.axhline(
        threshold_force,
        color="#A0A0A0",
        linestyle="--",
        linewidth=0.9,
        alpha=0.9,
        label=f"{int(THRUST_EVENT_THRESHOLD_RATIO * 100)}% threshold",
    )
    ax.axvline(thrust_metrics["ignition_time"], color="#6CA77B", linestyle=":", linewidth=1.0, alpha=0.95)
    ax.axvline(thrust_metrics["burnout_time"], color="#D08A7B", linestyle=":", linewidth=1.0, alpha=0.95)
    ax.plot(
        thrust_metrics["peak_time"],
        thrust_metrics["peak_thrust"],
        marker="o",
        linestyle="None",
        color="#C62839",
        markersize=3.5,
        label="Peak thrust",
    )
    ax.fill_between(
        time[thrust_metrics["ignition_idx"]:thrust_metrics["burnout_idx"] + 1],
        filtered_force[thrust_metrics["ignition_idx"]:thrust_metrics["burnout_idx"] + 1],
        0,
        alpha=0.12,
        color="blue",
    )
    ax.set_title(f"Loadcell Summary - {INPUT_FILENAME}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    ax.set_xlim(0, plot_end_time)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.92)

    thrust_text = (
        f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N\n"
        f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s\n"
        f"Ignition duration: {thrust_metrics['burn_time'] * 1000:.1f} ms\n"
        f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms"
    )
    ax.text(
        0.98,
        0.03,
        thrust_text,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.95),
    )

    plt.tight_layout()

    if SAVE_PLOT:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_loadcell_summary.png"
        plt.savefig(plot_path, dpi=300, bbox_inches="tight", facecolor="white")


def plot_barometer_summary(
    time: np.ndarray,
    raw_gauge_pressure: np.ndarray,
    filtered_gauge_pressure: np.ndarray,
    thrust_metrics: Dict[str, object],
    pressure_metrics: Dict[str, float],
) -> None:
    """Create a dedicated barometer/pressure figure."""
    fig, ax = plt.subplots(figsize=(13, 5.5))
    plot_end_time = min(time[-1], thrust_metrics["burnout_time"] + max(0.2, 0.25 * thrust_metrics["burn_time"]))

    ax.plot(time, raw_gauge_pressure, color="#5BA8A0", linewidth=0.8, alpha=0.6, label="Raw gauge pressure")
    ax.plot(
        time,
        filtered_gauge_pressure,
        color="#244EAD",
        linewidth=1.8,
        label="Filtered gauge pressure",
    )
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.4)
    ax.plot(
        pressure_metrics["peak_pressure_time"],
        pressure_metrics["peak_pressure"],
        "o",
        color="#237A45",
        markersize=3.5,
        label="Peak pressure",
    )
    ax.set_title(f"Barometer Summary - {INPUT_FILENAME}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(PRESSURE_LABEL)
    ax.set_xlim(0, plot_end_time)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.92)

    pressure_text = f"Peak pressure: {pressure_metrics['peak_pressure']:.3f}"
    ax.text(
        0.98,
        0.03,
        pressure_text,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.95),
    )

    plt.tight_layout()

    if SAVE_PLOT:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_barometer_summary.png"
        plt.savefig(plot_path, dpi=300, bbox_inches="tight", facecolor="white")


def save_report(
    thrust_metrics: Dict[str, object],
    pressure_metrics: Dict[str, float],
    drift_result: dict[str, object],
    pressure_baseline: float,
) -> None:
    """Save the text report as its own file."""
    if not SAVE_REPORT:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_executive_report.txt"

    with report_path.open("w", encoding="utf-8") as file:
        append_report_content(
            file,
            thrust_metrics,
            pressure_metrics,
            drift_result,
            pressure_baseline,
        )


def save_pipeline_data(
    time: np.ndarray,
    raw_force: np.ndarray,
    modeled_drift: np.ndarray,
    corrected_force: np.ndarray,
    filtered_force: np.ndarray,
    raw_gauge_pressure: np.ndarray,
    filtered_gauge_pressure: np.ndarray,
) -> None:
    """Save the processed pipeline data as its own file."""
    if not SAVE_DATA:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data_path = OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_pipeline_data.txt"
    np.savetxt(
        data_path,
        np.column_stack(
            (
                time,
                raw_force,
                modeled_drift,
                corrected_force,
                filtered_force,
                raw_gauge_pressure,
                filtered_gauge_pressure,
            )
        ),
        delimiter="\t",
        header=(
            "time_s\traw_force_N\tdrift_model_N\tcorrected_force_N\tfiltered_force_N\t"
            "raw_gauge_pressure\tfiltered_gauge_pressure"
        ),
        comments="",
        fmt="%.6f",
    )


def main() -> None:
    loadcell_adc = load_interleaved_channel(INPUT_FILE, LOADCELL_LINE_START)
    barometer_raw = load_interleaved_channel(INPUT_FILE, BAROMETER_LINE_START)
    drift_adc = load_single_channel_values(DRIFT_FILE) if DRIFT_MODE == "exponential" else np.array([], dtype=float)

    time = np.arange(loadcell_adc.size) / SAMPLING_RATE

    raw_force = calibrated_force(loadcell_adc)
    drift_force = calibrated_force(drift_adc) if drift_adc.size else None
    raw_pressure = convert_to_pressure(barometer_raw)

    drift_result = build_drift_result(DRIFT_MODE, time, raw_force, drift_force)
    modeled_drift = np.asarray(drift_result["modeled_drift"], dtype=float)
    corrected_force = np.asarray(drift_result["corrected_force"], dtype=float)
    filtered_force = zero_phase_lowpass(corrected_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    filtered_pressure = zero_phase_lowpass(raw_pressure, BAROMETER_LOWPASS_CUTOFF_HZ, BAROMETER_LOWPASS_ORDER)
    pressure_baseline = float(np.mean(filtered_pressure))
    raw_gauge_pressure = raw_pressure - pressure_baseline
    filtered_gauge_pressure = filtered_pressure - pressure_baseline

    thrust_metrics = calculate_thrust_metrics(time, filtered_force, PROPELLANT_MASS)
    pressure_metrics = calculate_pressure_metrics(time, filtered_gauge_pressure)

    save_report(
        thrust_metrics,
        pressure_metrics,
        drift_result,
        pressure_baseline,
    )
    save_pipeline_data(
        time,
        raw_force,
        modeled_drift,
        corrected_force,
        filtered_force,
        raw_gauge_pressure,
        filtered_gauge_pressure,
    )

    if GENERATE_PLOTS:
        plot_loadcell_summary(
            time,
            raw_force,
            corrected_force,
            filtered_force,
            thrust_metrics,
        )
        plot_barometer_summary(
            time,
            raw_gauge_pressure,
            filtered_gauge_pressure,
            thrust_metrics,
            pressure_metrics,
        )
        plt.show()
    print_terminal_summary(
        thrust_metrics,
        pressure_metrics,
        drift_result,
        loadcell_adc.size,
        barometer_raw.size,
        drift_adc.size,
    )


if __name__ == "__main__":
    main()
