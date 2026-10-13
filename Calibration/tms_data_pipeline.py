import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt

# ===== CONFIGURATION =====
YEAR = "2026"
DATE_FOLDER = "10_13"
INPUT_FILENAME = "TMS_4.TXT"
LOADCELL_CHANNEL_INDEX = 0
BAROMETER_CHANNEL_INDEX = 1
SKIP_INITIAL_LINES = 2
SAMPLING_RATE = 320

# Load cell calibration
CALIBRATION_SLOPE = -0.0391
CALIBRATION_INTERCEPT = -193.0049
CALIBRATION_R_SQUARED = 0.999948
GRAVITATIONAL_CONSTANT = 9.80665
FORCE_OFFSET = 0.0

# Drift correction
DRIFT_MODE = "horizontal"  # "off" or "horizontal"

# Signal filtering
LOADCELL_LOWPASS_CUTOFF_HZ = 20.0
LOADCELL_LOWPASS_ORDER = 2
BAROMETER_LOWPASS_CUTOFF_HZ = 5.0
BAROMETER_LOWPASS_ORDER = 4
PRESSURE_BASELINE_WINDOW_SECONDS = 0.5

# Pressure conversion
PRESSURE_SLOPE = 0.0027
PRESSURE_INTERCEPT = -0.11
PRESSURE_LABEL = "Gauge Pressure [bar]"

# Analysis
PROPELLANT_MASS = None
THRUST_EVENT_THRESHOLD_RATIO = 0.03
THRESHOLD_PERCENT = int(THRUST_EVENT_THRESHOLD_RATIO * 100)

# Outputs
GENERATE_PLOTS = True
SAVE_PLOT = True
SAVE_REPORT = True
SAVE_DATA = True
OUTPUT_FOLDER_NAME = "analysis"
PLOT_DPI = 600

# Plot palette
FORCE_RAW_COLOR = "#9FA9B5"
FORCE_FILTERED_COLOR = "#355C8A"
FORCE_PEAK_COLOR = "#4F86C6"
PRESSURE_RAW_COLOR = "#9EBFA7"
PRESSURE_FILTERED_COLOR = "#3F7A5C"
PRESSURE_PEAK_COLOR = "#5FA36F"
THRESHOLD_COLOR = "#7F7F7F"
ZERO_LINE_COLOR = "#4C4C4C"
IGNITION_MARK_COLOR = "#6E8AA5"
BURNOUT_MARK_COLOR = "#9A8F7A"
PRE_IGNITION_BG = "#F4F7FC"
BURN_BG = "#FBF1F6"
POST_BURN_BG = "#F2F8F1"
# =========================

FORCE_CORRECTED_LABEL = "Unfiltered corrected force"
FORCE_FILTERED_LABEL = "Filtered corrected force"
FORCE_PEAK_LABEL = "Peak force"
PRESSURE_RAW_LABEL = "Unfiltered gauge pressure"
PRESSURE_FILTERED_LABEL = "Filtered gauge pressure"
PRESSURE_PEAK_LABEL = "Peak pressure"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER
INPUT_FILE = DATA_DIR / INPUT_FILENAME
OUTPUT_DIR = DATA_DIR / OUTPUT_FOLDER_NAME
REPORT_RULE = "=" * 72
SECTION_RULE = "-" * 72
INTERLEAVED_CHANNEL_COUNT = 2
OUTPUT_PREFIX = None
SHOW_PLOTS = True


# ===== INPUT LOADING =====
def load_recording(file_path: str | Path) -> dict[str, object]:
    """Read the two uptime header lines, then paired signed 16-bit ADC values.

    A two-line file is the firmware's setup probe, not a timed recording.
    Calendar dates and individual sample timestamps are absent from this format.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]

    if len(lines) <= SKIP_INITIAL_LINES:
        raise ValueError(f"{file_path.name}: startup-only file; no timed samples")
    try:
        values = np.array([int(line) for line in lines], dtype=np.int64)
    except ValueError as exc:
        raise ValueError(f"{file_path.name}: expected one integer per line") from exc
    header, payload = values[:SKIP_INITIAL_LINES], values[SKIP_INITIAL_LINES:]
    if payload.size % INTERLEAVED_CHANNEL_COUNT:
        raise ValueError(f"{file_path.name}: incomplete loadcell/pressure pair")
    if np.any((payload < -32768) | (payload > 32767)):
        raise ValueError(f"{file_path.name}: ADC sample outside signed 16-bit range")
    if header.size != 2 or np.any(header < 0) or np.any(header > 2**32 - 1):
        raise ValueError(f"{file_path.name}: invalid uptime header")
    return {
        "sampling_start_us": int(header[0]), "power_on_us": int(header[1]),
        "loadcell_adc": payload[LOADCELL_CHANNEL_INDEX::2].astype(float),
        "pressure_adc": payload[BAROMETER_CHANNEL_INDEX::2].astype(float),
    }


def load_interleaved_channel(file_path: str | Path, channel_index: int) -> np.ndarray:
    """Skip header lines BEFORE splitting; preserve the first sensor pair."""
    if channel_index not in (LOADCELL_CHANNEL_INDEX, BAROMETER_CHANNEL_INDEX):
        raise ValueError("channel_index must be 0 or 1")
    recording = load_recording(file_path)
    return recording["loadcell_adc" if channel_index == LOADCELL_CHANNEL_INDEX else "pressure_adc"]


# ===== SIGNAL CONVERSION AND CORRECTION =====
def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    """Convert loadcell ADC values to force in Newtons."""
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def convert_to_pressure(raw_values: np.ndarray) -> np.ndarray:
    """Convert barometer channel values to pressure using the provided linear calibration."""
    return PRESSURE_SLOPE * raw_values + PRESSURE_INTERCEPT


def zero_phase_lowpass(values: np.ndarray, cutoff_hz: float, order: int) -> np.ndarray:
    """Apply a zero-phase Butterworth low-pass filter."""
    if values.size < 3:
        return values.copy()

    nyquist_hz = 0.5 * SAMPLING_RATE
    if cutoff_hz <= 0 or cutoff_hz >= nyquist_hz:
        raise ValueError(f"cutoff_hz must be between 0 and {nyquist_hz:.2f} Hz")

    b, a = butter(order, cutoff_hz / nyquist_hz, btype="low")
    padlen = 3 * max(len(a), len(b))
    if values.size <= padlen:
        return values.copy()
    return filtfilt(b, a, values)


def find_event_bounds(signal: np.ndarray, threshold_ratio: float) -> dict[str, float | int]:
    """Find the first and last threshold crossings for a positive-going event."""
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


def calculate_horizontal_offset(raw_force: np.ndarray) -> dict[str, float]:
    """Average raw loadcell force from start to half the detected ignition-start time."""
    filtered_force = zero_phase_lowpass(raw_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    seed_count = max(5, min(filtered_force.size, int(0.5 * SAMPLING_RATE)))
    baseline_seed = float(np.mean(filtered_force[:seed_count]))
    peak_force = float(np.max(filtered_force))
    trigger_force = baseline_seed + THRUST_EVENT_THRESHOLD_RATIO * (peak_force - baseline_seed)
    ignition_candidates = np.where(filtered_force >= trigger_force)[0]
    ignition_idx = int(ignition_candidates[0]) if ignition_candidates.size else filtered_force.size - 1
    averaging_end_idx = max(1, ignition_idx // 2)
    offset_force = float(np.mean(raw_force[:averaging_end_idx]))
    return {
        "offset_force": offset_force,
        "averaging_end_idx": averaging_end_idx,
        "averaging_end_time_s": averaging_end_idx / SAMPLING_RATE,
        "ignition_time_s": ignition_idx / SAMPLING_RATE,
    }


def apply_drift_correction(raw_force: np.ndarray) -> dict[str, object]:
    """Apply the selected normal-use drift mode."""
    if DRIFT_MODE == "off":
        return {
            "mode": "off",
            "label": "Off",
            "description": "No drift correction applied.",
            "modeled_drift": np.zeros_like(raw_force),
            "corrected_force": raw_force.copy(),
        }

    if DRIFT_MODE == "horizontal":
        offset_result = calculate_horizontal_offset(raw_force)
        offset_force = float(offset_result["offset_force"])
        return {
            "mode": "horizontal",
            "label": "Constant baseline offset",
            "description": (
                f"Constant offset from the average raw loadcell force up to half the ignition-start time: "
                f"{offset_force:.6f} N (through {offset_result['averaging_end_time_s']:.6f} s, "
                f"{offset_result['averaging_end_idx']} samples; ignition start at "
                f"{offset_result['ignition_time_s']:.6f} s)"
            ),
            "modeled_drift": np.full_like(raw_force, offset_force, dtype=float),
            "corrected_force": raw_force - offset_force,
            "offset_force": offset_force,
            "averaging_end_idx": int(offset_result["averaging_end_idx"]),
            "averaging_end_time_s": float(offset_result["averaging_end_time_s"]),
            "ignition_time_s": float(offset_result["ignition_time_s"]),
        }

    raise ValueError(f"Unsupported DRIFT_MODE: {DRIFT_MODE}. Use 'off' or 'horizontal'.")


def calculate_pressure_baseline(pressure_values: np.ndarray) -> float:
    """Estimate the barometer zero offset from the initial idle window."""
    if pressure_values.size == 0:
        return 0.0

    baseline_count = max(5, min(pressure_values.size, int(PRESSURE_BASELINE_WINDOW_SECONDS * SAMPLING_RATE)))
    return float(np.mean(pressure_values[:baseline_count]))


# ===== METRICS =====
def calculate_pressure_metrics(time: np.ndarray, filtered_gauge_pressure: np.ndarray) -> dict[str, float]:
    """Calculate peak pressure metrics from the filtered gauge-pressure trace."""
    peak_idx = int(np.argmax(filtered_gauge_pressure))
    return {
        "peak_pressure": float(filtered_gauge_pressure[peak_idx]),
        "peak_pressure_time": float(time[peak_idx]),
    }


def calculate_thrust_metrics(
    time: np.ndarray,
    filtered_force: np.ndarray,
    propellant_mass: float | None = None,
) -> dict[str, object]:
    """Calculate thrust metrics from the filtered corrected force trace."""
    dt = time[1] - time[0] if len(time) > 1 else 1.0 / SAMPLING_RATE
    event = find_event_bounds(filtered_force, THRUST_EVENT_THRESHOLD_RATIO)
    peak_idx = int(event["peak_idx"])
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

    return {
        "peak_thrust": float(event["peak_value"]),
        "peak_time": float(time[peak_idx]),
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
        "threshold_force": float(event["threshold_value"]),
    }


# ===== REPORT AND SAVED-DATA OUTPUT =====
def get_output_path(suffix: str) -> Path:
    """Build an output path for the current input file."""
    return OUTPUT_DIR / f"{OUTPUT_PREFIX or Path(INPUT_FILENAME).stem}_{suffix}"


def ensure_output_dir() -> None:
    """Create the analysis output directory when needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def format_project_relative_path(path: str | Path) -> str:
    """Return a report-friendly path rooted at the project folder name."""
    path = Path(path).resolve()
    try:
        relative_path = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return str(path)
    return str(Path(PROJECT_ROOT.name) / relative_path)


def write_report_section(file, title: str, lines: list[str]) -> None:
    """Write one report section with consistent formatting."""
    file.write(f"{SECTION_RULE}\n")
    file.write(f"{title}\n")
    file.write(f"{SECTION_RULE}\n")
    file.write("\n".join(lines))
    file.write("\n\n")


def save_report(
    thrust_metrics: dict[str, object],
    pressure_metrics: dict[str, float],
    drift_result: dict[str, object],
    pressure_baseline: float,
    quality: dict | None = None,
) -> None:
    """Save the executive report as a text file."""
    if not SAVE_REPORT:
        return

    ensure_output_dir()
    report_path = get_output_path("executive_report.txt")

    with report_path.open("w", encoding="utf-8") as file:
        file.write(f"{REPORT_RULE}\n")
        file.write("STATIC FIRE REPORT\n")
        file.write(f"{REPORT_RULE}\n\n")
        file.write(f"Input file: {format_project_relative_path(INPUT_FILE)}\n")
        file.write(f"Sampling rate: {SAMPLING_RATE} sps\n\n")

        if quality:
            write_report_section(file, "DATA QUALITY", [
                f"Thrust status: {quality['thrust_status']}",
                f"Pressure status: {quality['pressure_status']}",
                "Time axis assumes uniform 320 Hz sampling; no per-sample timestamps are logged.",
                "Ignition delay is time from recording start, not an independently logged fire command.",
                "Calibration is inherited from the existing pipeline; no same-day calibration was supplied.",
                *quality["warnings"],
            ])

        performance_lines = [
            f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms",
            f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N",
            f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s",
            f"Average thrust: {thrust_metrics['avg_thrust']:.2f} N",
            f"Burn duration: {thrust_metrics['burn_time'] * 1000:.1f} ms",
        ]
        if thrust_metrics["specific_impulse"] is not None:
            performance_lines.append(f"Specific impulse: {thrust_metrics['specific_impulse']:.1f} s")
        if quality and quality["thrust_status"] == "no_event":
            performance_lines = ["No sustained thrust event above the noise gate; performance metrics unavailable."]
        elif quality and quality["thrust_status"] == "provisional":
            performance_lines.insert(0, "PROVISIONAL: baseline shift contaminates the 3% end threshold and integration window.")
        write_report_section(file, "THRUST METRICS", performance_lines)

        pressure_lines = [
            f"Peak pressure: {pressure_metrics['peak_pressure']:.3f} bar at {pressure_metrics['peak_pressure_time']:.3f} s",
        ]
        if quality and quality["pressure_status"] != "usable":
            pressure_lines = ["Unavailable: ADC channel is clipped or stuck; baseline subtraction cannot recover pressure."]
        write_report_section(file, "PRESSURE METRICS", pressure_lines)

        write_report_section(
            file,
            "CALIBRATION",
            [
                f"Loadcell calibration slope: {CALIBRATION_SLOPE:.6f} kg/ADC",
                f"Loadcell calibration intercept: {CALIBRATION_INTERCEPT:.4f} kg",
                f"Loadcell calibration R^2: {CALIBRATION_R_SQUARED:.6f}",
                f"Pressure conversion: y = {PRESSURE_SLOPE}x {PRESSURE_INTERCEPT:+.2f}",
            ],
        )

        processing_lines = [
            f"Drift correction: {drift_result['label']}",
            "Thrust metrics are calculated from filtered corrected force.",
            "Pressure metrics are calculated from filtered gauge pressure.",
            f"Loadcell threshold ({THRESHOLD_PERCENT} percent): {thrust_metrics['threshold_force']:.2f} N",
            f"Loadcell filter: Butterworth low-pass {LOADCELL_LOWPASS_CUTOFF_HZ:.1f} Hz, order {LOADCELL_LOWPASS_ORDER}",
            f"Pressure filter: Butterworth low-pass {BAROMETER_LOWPASS_CUTOFF_HZ:.1f} Hz, order {BAROMETER_LOWPASS_ORDER}",
            f"Pressure baseline offset: {pressure_baseline:.6f} bar",
            f"Pressure baseline window: first {PRESSURE_BASELINE_WINDOW_SECONDS:.3f} s (up to {int(PRESSURE_BASELINE_WINDOW_SECONDS * SAMPLING_RATE)} samples, filtered pressure)",
            "Loadcell offset is measured from pre-event raw force and subtracted before filtering.",
            "Pressure validity is checked before any offset subtraction; invalid channels remain unavailable.",
        ]
        if drift_result["mode"] == "horizontal":
            processing_lines.extend(
                [
                    f"Loadcell baseline offset: {drift_result['offset_force']:.6f} N",
                    f"Loadcell baseline window end: {drift_result['averaging_end_time_s']:.6f} s "
                    f"({drift_result['averaging_end_idx']} samples)",
                    f"Ignition start time: {drift_result['ignition_time_s']:.6f} s",
                ]
            )
        else:
            processing_lines.append(f"Details: {drift_result['description']}")
        write_report_section(file, "DATA PROCESSING", processing_lines)

        file.write(f"{REPORT_RULE}\n")


def save_pipeline_data(
    time: np.ndarray,
    raw_force: np.ndarray,
    modeled_drift: np.ndarray,
    corrected_force: np.ndarray,
    filtered_force: np.ndarray,
    raw_gauge_pressure: np.ndarray,
    filtered_gauge_pressure: np.ndarray,
    loadcell_adc: np.ndarray | None = None,
    pressure_adc: np.ndarray | None = None,
) -> None:
    """Save processed analysis data as a text file."""
    if not SAVE_DATA:
        return

    ensure_output_dir()
    data_path = get_output_path("pipeline_data.txt")
    columns = [time, raw_force, modeled_drift, corrected_force, filtered_force,
               raw_gauge_pressure, filtered_gauge_pressure]
    header = ("time_s\traw_force_N\tdrift_model_N\tcorrected_force_N\tfiltered_force_N\t"
              "raw_gauge_pressure\tfiltered_gauge_pressure")
    if loadcell_adc is not None and pressure_adc is not None:
        columns.extend([loadcell_adc, pressure_adc])
        header += "\tloadcell_adc\tpressure_adc"
    np.savetxt(
        data_path,
        np.column_stack(columns),
        delimiter="\t",
        header=header,
        comments="",
        fmt="%.6f",
    )


def print_terminal_summary(
    thrust_metrics: dict[str, object],
    pressure_metrics: dict[str, float],
    drift_result: dict[str, object],
    loadcell_samples: int,
    barometer_samples: int,
) -> None:
    """Print only the essential run information to the terminal."""
    print("Run complete")
    print(f"Samples used: loadcell={loadcell_samples}, barometer={barometer_samples}")
    summary_lines = [
        f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N",
        f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s",
        f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms",
        f"Burn time: {thrust_metrics['burn_time'] * 1000:.1f} ms",
        f"Peak pressure: {pressure_metrics['peak_pressure']:.3f}",
        f"Drift mode: {drift_result['label']}",
    ]
    for line in summary_lines:
        print(line)
    print(f"Output folder: {format_project_relative_path(OUTPUT_DIR)}")


# ===== PLOTTING =====
def save_current_figure(filename: str) -> None:
    """Save the current figure into the analysis output folder."""
    if not SAVE_PLOT:
        return

    ensure_output_dir()
    plt.savefig(get_output_path(filename), dpi=PLOT_DPI, bbox_inches="tight", facecolor="white")


def get_plot_end_time(time: np.ndarray, thrust_metrics: dict[str, object]) -> float:
    """Clamp plots to the burn plus a short post-burn margin."""
    return min(time[-1], thrust_metrics["burnout_time"] + max(0.2, 0.25 * thrust_metrics["burn_time"]))


def align_dual_axis_zero(ax_left, ax_right) -> None:
    """Make both y-axes share the same zero location."""
    for axis in (ax_left, ax_right):
        ymin, ymax = axis.get_ylim()
        limit = max(abs(float(ymin)), abs(float(ymax)))
        axis.set_ylim(-max(limit, 1.0), max(limit, 1.0))


def add_pastel_test_background(ax, time: np.ndarray, thrust_metrics: dict[str, object]) -> None:
    """Add the same pastel phase background used across all plots."""
    ax.axvspan(0, thrust_metrics["ignition_time"], color=PRE_IGNITION_BG, alpha=0.95, lw=0)
    ax.axvspan(thrust_metrics["ignition_time"], thrust_metrics["burnout_time"], color=BURN_BG, alpha=0.98, lw=0)
    ax.axvspan(thrust_metrics["burnout_time"], time[-1], color=POST_BURN_BG, alpha=0.98, lw=0)
    ax.set_facecolor("white")


def add_metric_box(ax, text: str) -> None:
    """Draw a small summary box in the bottom-right corner of a plot."""
    ax.text(
        0.98,
        0.03,
        text,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.95),
    )


def plot_loadcell_summary(
    time: np.ndarray,
    corrected_force: np.ndarray,
    filtered_force: np.ndarray,
    thrust_metrics: dict[str, object],
) -> None:
    """Create a dedicated loadcell/thrust figure."""
    fig, ax = plt.subplots(figsize=(13, 6.5))
    plot_end_time = get_plot_end_time(time, thrust_metrics)
    threshold_force = thrust_metrics["threshold_force"]

    add_pastel_test_background(ax, time, thrust_metrics)
    ax.plot(time, corrected_force, color=FORCE_RAW_COLOR, linewidth=1.15, alpha=0.9, label=FORCE_CORRECTED_LABEL)
    ax.plot(time, filtered_force, color=FORCE_FILTERED_COLOR, linewidth=2.1, label=FORCE_FILTERED_LABEL)
    ax.axhline(0, color=ZERO_LINE_COLOR, linewidth=0.6, alpha=0.45)
    ax.axhline(
        threshold_force,
        color=THRESHOLD_COLOR,
        linestyle="--",
        linewidth=0.9,
        alpha=0.9,
        label=f"{THRESHOLD_PERCENT}% threshold",
    )
    ax.axvline(thrust_metrics["ignition_time"], color=IGNITION_MARK_COLOR, linestyle=":", linewidth=1.0, alpha=0.95)
    ax.axvline(thrust_metrics["burnout_time"], color=BURNOUT_MARK_COLOR, linestyle=":", linewidth=1.0, alpha=0.95)
    ax.plot(
        thrust_metrics["peak_time"],
        thrust_metrics["peak_thrust"],
        marker="o",
        linestyle="None",
        color=FORCE_PEAK_COLOR,
        markersize=3.5,
        label=FORCE_PEAK_LABEL,
    )
    ax.fill_between(
        time[thrust_metrics["ignition_idx"]:thrust_metrics["burnout_idx"] + 1],
        filtered_force[thrust_metrics["ignition_idx"]:thrust_metrics["burnout_idx"] + 1],
        0,
        alpha=0.12,
        color=FORCE_FILTERED_COLOR,
    )

    ax.set_title(f"Loadcell Graph - {INPUT_FILENAME}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    ax.set_xlim(0, plot_end_time)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.92)

    thrust_text = (
        f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N\n"
        f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s\n"
        f"Burn duration: {thrust_metrics['burn_time'] * 1000:.1f} ms\n"
        f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms"
    )
    add_metric_box(ax, thrust_text)

    plt.tight_layout()
    save_current_figure("loadcell_plot.png")


def plot_barometer_summary(
    time: np.ndarray,
    raw_gauge_pressure: np.ndarray,
    filtered_gauge_pressure: np.ndarray,
    thrust_metrics: dict[str, object],
    pressure_metrics: dict[str, float],
) -> None:
    """Create a dedicated barometer/pressure figure."""
    fig, ax = plt.subplots(figsize=(13, 5.5))
    plot_end_time = get_plot_end_time(time, thrust_metrics)

    add_pastel_test_background(ax, time, thrust_metrics)
    ax.plot(time, raw_gauge_pressure, color=PRESSURE_RAW_COLOR, linewidth=1.15, alpha=0.88, label=PRESSURE_RAW_LABEL)
    ax.plot(time, filtered_gauge_pressure, color=PRESSURE_FILTERED_COLOR, linewidth=2.0, label=PRESSURE_FILTERED_LABEL)
    ax.axhline(0, color=ZERO_LINE_COLOR, linewidth=0.6, alpha=0.45)
    ax.plot(
        pressure_metrics["peak_pressure_time"],
        pressure_metrics["peak_pressure"],
        "o",
        color=PRESSURE_PEAK_COLOR,
        markersize=3.5,
        label=PRESSURE_PEAK_LABEL,
    )
    ax.axvline(thrust_metrics["burnout_time"], color=BURNOUT_MARK_COLOR, linestyle=":", linewidth=1.0, alpha=0.95)

    ax.set_title(f"Barometer Graph - {INPUT_FILENAME}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(PRESSURE_LABEL)
    ax.set_xlim(0, plot_end_time)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.92)
    add_metric_box(ax, f"Peak pressure: {pressure_metrics['peak_pressure']:.3f}")

    plt.tight_layout()
    save_current_figure("barometer_plot.png")


def plot_combined_loadcell_barometer(
    time: np.ndarray,
    corrected_force: np.ndarray,
    filtered_force: np.ndarray,
    raw_gauge_pressure: np.ndarray,
    filtered_gauge_pressure: np.ndarray,
    thrust_metrics: dict[str, object],
    pressure_metrics: dict[str, float],
) -> None:
    """Create a combined figure with one shared time axis."""
    fig, ax_force = plt.subplots(figsize=(13, 6.5))
    ax_pressure = ax_force.twinx()
    plot_end_time = get_plot_end_time(time, thrust_metrics)

    add_pastel_test_background(ax_force, time, thrust_metrics)
    ax_pressure.patch.set_alpha(0.0)
    force_corrected_line, = ax_force.plot(
        time,
        corrected_force,
        color=FORCE_RAW_COLOR,
        linewidth=0.9,
        alpha=0.75,
        label=FORCE_CORRECTED_LABEL,
    )
    force_filtered_line, = ax_force.plot(
        time,
        filtered_force,
        color=FORCE_FILTERED_COLOR,
        linewidth=2.1,
        label=FORCE_FILTERED_LABEL,
    )
    force_peak_line, = ax_force.plot(
        thrust_metrics["peak_time"],
        thrust_metrics["peak_thrust"],
        marker="o",
        linestyle="None",
        color=FORCE_PEAK_COLOR,
        markersize=4.0,
        label=FORCE_PEAK_LABEL,
    )
    ax_force.axhline(0, color=ZERO_LINE_COLOR, linewidth=0.6, alpha=0.45)
    ax_force.axvline(thrust_metrics["ignition_time"], color=IGNITION_MARK_COLOR, linestyle=":", linewidth=1.0, alpha=0.95)
    ax_force.axvline(thrust_metrics["burnout_time"], color=BURNOUT_MARK_COLOR, linestyle=":", linewidth=1.0, alpha=0.95)
    ax_force.set_xlabel("Time (s)")
    ax_force.set_ylabel("Force (N)", color=FORCE_FILTERED_COLOR)
    ax_force.tick_params(axis="y", labelcolor=FORCE_FILTERED_COLOR)

    pressure_raw_line, = ax_pressure.plot(
        time,
        raw_gauge_pressure,
        color=PRESSURE_RAW_COLOR,
        linewidth=0.9,
        alpha=0.65,
        label=PRESSURE_RAW_LABEL,
    )
    pressure_filtered_line, = ax_pressure.plot(
        time,
        filtered_gauge_pressure,
        color=PRESSURE_FILTERED_COLOR,
        linewidth=2.0,
        alpha=0.95,
        label=PRESSURE_FILTERED_LABEL,
    )
    ax_pressure.axhline(0, color=ZERO_LINE_COLOR, linewidth=0.6, alpha=0.45)
    pressure_peak_line, = ax_pressure.plot(
        pressure_metrics["peak_pressure_time"],
        pressure_metrics["peak_pressure"],
        marker="o",
        linestyle="None",
        color=PRESSURE_PEAK_COLOR,
        markersize=4.0,
        label=PRESSURE_PEAK_LABEL,
    )
    ax_pressure.set_ylabel(PRESSURE_LABEL, color=PRESSURE_FILTERED_COLOR)
    ax_pressure.tick_params(axis="y", labelcolor=PRESSURE_FILTERED_COLOR)
    align_dual_axis_zero(ax_force, ax_pressure)

    ax_force.set_title(f"Loadcell + Barometer Graph - {INPUT_FILENAME}")
    ax_force.set_xlim(0, plot_end_time)
    ax_force.grid(True, alpha=0.3)

    lines = [
        force_corrected_line,
        force_filtered_line,
        force_peak_line,
        pressure_raw_line,
        pressure_filtered_line,
        pressure_peak_line,
    ]
    ax_force.legend(lines, [line.get_label() for line in lines], loc="upper left", fontsize=8, ncol=2, framealpha=0.92)

    plt.tight_layout()
    save_current_figure("combined_plot.png")


def assess_channels(loadcell_adc: np.ndarray, pressure_adc: np.ndarray) -> dict:
    """Conservative validity gate before baseline subtraction can hide failures."""
    raw_force = calibrated_force(loadcell_adc)
    seed = raw_force[:min(raw_force.size, int(0.5 * SAMPLING_RATE))]
    noise = float(np.std(seed))
    gate = max(5.0, 10.0 * noise)
    filtered = zero_phase_lowpass(raw_force - np.mean(seed), LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    above = filtered > gate
    sustained = max(1, int(0.1 * SAMPLING_RATE))
    has_event = bool(above.size >= sustained and np.any(np.convolve(above.astype(int), np.ones(sustained, dtype=int), mode="valid") == sustained))
    clipped = (pressure_adc >= 32767) | (pressure_adc <= -32768)
    load_clipped = (loadcell_adc >= 32767) | (loadcell_adc <= -32768)
    pressure_status = "invalid_saturated" if np.any(clipped) else "invalid_stuck" if np.ptp(pressure_adc) == 0 else "usable"
    return {
        "thrust_status": "provisional" if np.any(load_clipped) else "event_detected" if has_event else "no_event",
        "event_detected": has_event,
        "loadcell_clipped_samples": int(np.sum(load_clipped)),
        "pressure_status": pressure_status,
        "pressure_clipped_samples": int(np.sum(clipped)),
        "pressure_unique_codes": int(np.unique(pressure_adc).size),
        "baseline_raw_std_N": noise,
        "event_gate_N": gate,
        "event_gate_duration_s": sustained / SAMPLING_RATE,
        "warnings": ["Pressure metrics withheld: raw ADC is clipped or stuck."] if pressure_status != "usable" else [],
    }


def json_safe(value):
    """Strict JSON uses null for unavailable metrics, never NaN or a false zero."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def pipeline_revision() -> dict:
    """Identify the commit containing this code, only if its bytes are committed."""
    try:
        relative = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
        current = subprocess.run(["git", "-C", str(PROJECT_ROOT), "show", f"HEAD:{relative}"], capture_output=True, check=True)
        modified = current.stdout != Path(__file__).read_bytes()
        revision = subprocess.run(["git", "-C", str(PROJECT_ROOT), "log", "-1", "--format=%H", "--", relative], capture_output=True, text=True, check=True).stdout.strip()
        return {"code_commit": None if modified else revision, "working_tree_modified": modified}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {"code_commit": None, "working_tree_modified": None}


def plot_quality_diagnostics(time, corrected, filtered, pressure_adc, quality, metrics):
    """Show the entire recording, including post-event offset and failed ADC."""
    for kind in ("loadcell", "barometer", "combined"):
        fig, ax = plt.subplots(figsize=(12, 5.5))
        if kind == "barometer":
            ax.plot(time, pressure_adc, color=PRESSURE_FILTERED_COLOR, label="Recorded pressure ADC")
            ax.set_ylabel("Pressure ADC (counts)")
            ax.set_ylim(32760, 32770) if np.all(pressure_adc == 32767) else None
        else:
            ax.plot(time, corrected, color=FORCE_RAW_COLOR, alpha=.65, linewidth=.8, label="Baseline-corrected force")
            ax.plot(time, filtered, color=FORCE_FILTERED_COLOR, linewidth=1.7, label="Filtered force")
            ax.set_ylabel("Force (N)")
            if quality["event_detected"]:
                ax.axvline(metrics["ignition_time"], color=IGNITION_MARK_COLOR, linestyle=":", label="3% onset")
                ax.axhline(metrics["threshold_force"], color=THRESHOLD_COLOR, linestyle="--", label="3% threshold")
            if kind == "combined":
                ax.text(.02, .96, "Pressure unavailable: raw ADC clipped/stuck", transform=ax.transAxes, va="top", color=PRESSURE_FILTERED_COLOR)
        ax.set_title(f"{INPUT_FILENAME} | {quality['thrust_status']} thrust | {quality['pressure_status']} pressure")
        ax.set_xlabel("Time from recording start (s), nominal 320 Hz")
        ax.set_xlim(time[0], time[-1])
        ax.grid(alpha=.25)
        ax.legend(loc="upper right")
        if quality["thrust_status"] == "provisional" and kind != "barometer":
            ax.text(.02, .04, "Post-event offset affects burn end and impulse; see quality report", transform=ax.transAxes)
        fig.tight_layout()
        save_current_figure(f"{kind}_plot.png")
        plt.close(fig)


def main() -> dict:
    recording = load_recording(INPUT_FILE)
    loadcell_adc, barometer_raw = recording["loadcell_adc"], recording["pressure_adc"]
    time = np.arange(loadcell_adc.size) / SAMPLING_RATE
    quality = assess_channels(loadcell_adc, barometer_raw)
    raw_force = calibrated_force(loadcell_adc)
    if quality["event_detected"]:
        drift_result = apply_drift_correction(raw_force)
    else:
        count = min(raw_force.size, int(.5 * SAMPLING_RATE))
        offset = float(np.mean(raw_force[:count]))
        drift_result = {"mode": "horizontal", "label": "Initial idle baseline (no event)",
                        "modeled_drift": np.full_like(raw_force, offset), "corrected_force": raw_force - offset,
                        "offset_force": offset, "averaging_end_idx": count,
                        "averaging_end_time_s": count / SAMPLING_RATE, "ignition_time_s": float("nan")}
    modeled_drift, corrected_force = drift_result["modeled_drift"], drift_result["corrected_force"]
    filtered_force = zero_phase_lowpass(corrected_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)
    if quality["pressure_status"] == "usable":
        raw_pressure = convert_to_pressure(barometer_raw)
        filtered_pressure = zero_phase_lowpass(raw_pressure, BAROMETER_LOWPASS_CUTOFF_HZ, BAROMETER_LOWPASS_ORDER)
        pressure_baseline = calculate_pressure_baseline(filtered_pressure)
        raw_gauge_pressure, filtered_gauge_pressure = raw_pressure - pressure_baseline, filtered_pressure - pressure_baseline
        pressure_metrics = calculate_pressure_metrics(time, filtered_gauge_pressure)
    else:
        pressure_baseline = float("nan")
        raw_gauge_pressure = np.full_like(time, np.nan)
        filtered_gauge_pressure = np.full_like(time, np.nan)
        pressure_metrics = {"peak_pressure": float("nan"), "peak_pressure_time": float("nan")}
    if quality["event_detected"]:
        thrust_metrics = calculate_thrust_metrics(time, filtered_force, PROPELLANT_MASS)
        tail = filtered_force[-min(filtered_force.size, SAMPLING_RATE):]
        quality["tail_mean_N"], quality["tail_std_N"] = float(np.mean(tail)), float(np.std(tail))
        if abs(quality["tail_mean_N"]) >= .5 * thrust_metrics["threshold_force"]:
            quality["thrust_status"] = "provisional"
            quality["warnings"].append("Post-event baseline is at least half the 3% thrust threshold; burn end, average thrust, and impulse are provisional.")
        quality["burn_end_censored"] = thrust_metrics["burnout_idx"] >= len(time) - 1
        if quality["burn_end_censored"]:
            quality["thrust_status"] = "provisional"
            quality["warnings"].append("Last threshold crossing is at the end of the recording; burn duration is not validated.")
    else:
        thrust_metrics = {k: float("nan") for k in ("peak_thrust", "peak_time", "ignition_time", "burnout_time", "burn_time", "ignition_delay", "total_impulse", "avg_thrust", "threshold_force")}
        thrust_metrics["specific_impulse"] = None
        quality["warnings"].append("No sustained thrust event; noise is not published as a combustion test.")
    ensure_output_dir()
    save_report(thrust_metrics, pressure_metrics, drift_result, pressure_baseline, quality)
    save_pipeline_data(time, raw_force, modeled_drift, corrected_force, filtered_force,
                       raw_gauge_pressure, filtered_gauge_pressure, loadcell_adc, barometer_raw)
    if GENERATE_PLOTS:
        if quality["pressure_status"] != "usable" or not quality["event_detected"]:
            plot_quality_diagnostics(time, corrected_force, filtered_force, barometer_raw, quality, thrust_metrics)
        else:
            plot_loadcell_summary(time, corrected_force, filtered_force, thrust_metrics)
            plot_barometer_summary(time, raw_gauge_pressure, filtered_gauge_pressure, thrust_metrics, pressure_metrics)
            plot_combined_loadcell_barometer(time, corrected_force, filtered_force, raw_gauge_pressure, filtered_gauge_pressure, thrust_metrics, pressure_metrics)
            if SHOW_PLOTS:
                plt.show()
            plt.close("all")
    result = json_safe({
        "input_file": format_project_relative_path(INPUT_FILE),
        "input_sha256": hashlib.sha256(Path(INPUT_FILE).read_bytes()).hexdigest(),
        "pipeline_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pipeline_revision": pipeline_revision(),
        "sampling_start_us": recording["sampling_start_us"], "power_on_us": recording["power_on_us"],
        "sample_count": len(time), "sampling_rate_hz": SAMPLING_RATE,
        "nominal_last_sample_s": float(time[-1]), "nominal_coverage_s": len(time) / SAMPLING_RATE,
        "timing": "Uniform 320 Hz assumed, not verified; firmware targets 15 seconds and logs no per-sample timestamps.",
        "calibration": {"slope_kg_per_adc": CALIBRATION_SLOPE, "intercept_kg": CALIBRATION_INTERCEPT,
                        "r_squared": CALIBRATION_R_SQUARED, "same_day_calibration_supplied": False},
        "quality": quality, "thrust": thrust_metrics, "pressure": pressure_metrics,
        "baseline_offset_N": drift_result["offset_force"], "baseline_sample_count": drift_result["averaging_end_idx"],
    })
    get_output_path("quality.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{INPUT_FILENAME}: thrust={quality['thrust_status']}, pressure={quality['pressure_status']}, samples={len(time)}")
    return result


def cli() -> None:
    global INPUT_FILE, INPUT_FILENAME, OUTPUT_DIR, OUTPUT_PREFIX, SHOW_PLOTS, GENERATE_PLOTS, PLOT_DPI
    parser = argparse.ArgumentParser(description="Analyze a paired TMS recording; reject startup probes and withhold invalid pressure.")
    parser.add_argument("--input", type=Path, help="Raw TMS file; defaults to the configured legacy dataset")
    parser.add_argument("--output-dir", type=Path, help="Output directory; defaults to the selected input's analysis folder")
    parser.add_argument("--prefix", help="Output filename stem, e.g. 2026-10-13_tms-4")
    parser.add_argument("--no-show", action="store_true", help="Save figures without opening an interactive window")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--dpi", type=int, default=PLOT_DPI)
    args = parser.parse_args()
    if args.input:
        INPUT_FILE = args.input.resolve()
        INPUT_FILENAME = INPUT_FILE.name
        OUTPUT_DIR = INPUT_FILE.parent / OUTPUT_FOLDER_NAME
    if args.output_dir:
        OUTPUT_DIR = args.output_dir.resolve()
    OUTPUT_PREFIX, SHOW_PLOTS, GENERATE_PLOTS, PLOT_DPI = args.prefix, not args.no_show, not args.no_plots, args.dpi
    try:
        main()
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()
