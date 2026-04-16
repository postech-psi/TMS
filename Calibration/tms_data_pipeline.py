from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt

# ===== CONFIGURATION =====
YEAR = "2026"
DATE_FOLDER = "4_8"
INPUT_FILENAME = "2026.04.08 data.TXT"
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


# ===== INPUT LOADING =====
def load_interleaved_channel(file_path: str | Path, channel_index: int) -> np.ndarray:
    """Load one channel from an interleaved TMS text file."""
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]

    values = [float(lines[i]) for i in range(channel_index, len(lines), INTERLEAVED_CHANNEL_COUNT)]
    return np.array(values, dtype=float)[SKIP_INITIAL_LINES:]


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
    padlen = 3 * (max(len(a), len(b)) - 1)
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
    return OUTPUT_DIR / f"{Path(INPUT_FILENAME).stem}_{suffix}"


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
) -> None:
    """Save the executive report as a text file."""
    if not SAVE_REPORT:
        return

    ensure_output_dir()
    report_path = get_output_path("executive_report.txt")
    pressure_baseline_samples = max(5, int(PRESSURE_BASELINE_WINDOW_SECONDS * SAMPLING_RATE))

    with report_path.open("w", encoding="utf-8") as file:
        file.write(f"{REPORT_RULE}\n")
        file.write("STATIC FIRE REPORT\n")
        file.write(f"{REPORT_RULE}\n\n")
        file.write(f"Input file: {format_project_relative_path(INPUT_FILE)}\n")
        file.write(f"Sampling rate: {SAMPLING_RATE} sps\n\n")

        performance_lines = [
            f"Ignition delay: {thrust_metrics['ignition_delay'] * 1000:.1f} ms",
            f"Peak thrust: {thrust_metrics['peak_thrust']:.2f} N",
            f"Total impulse: {thrust_metrics['total_impulse']:.2f} N s",
            f"Average thrust: {thrust_metrics['avg_thrust']:.2f} N",
            f"Burn duration: {thrust_metrics['burn_time'] * 1000:.1f} ms",
        ]
        if thrust_metrics["specific_impulse"] is not None:
            performance_lines.append(f"Specific impulse: {thrust_metrics['specific_impulse']:.1f} s")
        write_report_section(file, "THRUST METRICS", performance_lines)

        pressure_lines = [
            f"Peak pressure: {pressure_metrics['peak_pressure']:.3f} bar at {pressure_metrics['peak_pressure_time']:.3f} s",
        ]
        write_report_section(file, "PRESSURE METRICS", pressure_lines)

        write_report_section(
            file, "CALIBRATION",
            [
                f"Loadcell calibration slope: {CALIBRATION_SLOPE:.6f} kg/ADC",
                f"Loadcell calibration intercept: {CALIBRATION_INTERCEPT:.4f} kg",
                f"Loadcell calibration R^2: {CALIBRATION_R_SQUARED:.6f}",
                f"Pressure conversion: y = {PRESSURE_SLOPE}x {PRESSURE_INTERCEPT:+.2f}",
            ],
        )

        loadcell_baseline_line = "Loadcell baseline offset: not applied"
        loadcell_window_line = "Loadcell baseline window: not used"
        if drift_result["mode"] == "horizontal":
            loadcell_baseline_line = f"Loadcell baseline offset: {drift_result['offset_force']:.6f} N"
            loadcell_window_line = (
                f"Loadcell baseline window: 0.000000 to {drift_result['averaging_end_time_s']:.6f} s "
                f"({drift_result['averaging_end_idx']} samples, pre-ignition raw force)"
            )
        processing_lines = [
            "Loadcell offset is measured from the pre-ignition raw-force window, then subtracted from raw force to create corrected force.",
            "Pressure offset is measured from the initial filtered-pressure window, then subtracted from both raw pressure and filtered pressure to create gauge pressure.",
            loadcell_baseline_line,
            f"Pressure baseline offset: {pressure_baseline:.6f} bar",
            loadcell_window_line,
            f"Pressure baseline window: first {PRESSURE_BASELINE_WINDOW_SECONDS:.3f} s ({pressure_baseline_samples} samples, filtered pressure)",
            f"Loadcell low-pass: applied to corrected force at {LOADCELL_LOWPASS_CUTOFF_HZ:.1f} Hz, order {LOADCELL_LOWPASS_ORDER}",
            f"Pressure low-pass: applied to raw pressure at {BAROMETER_LOWPASS_CUTOFF_HZ:.1f} Hz, order {BAROMETER_LOWPASS_ORDER}",
            f"Threshold: {thrust_metrics['threshold_force']:.2f} N ({THRESHOLD_PERCENT}% of peak filtered force)",
        ]
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
) -> None:
    """Save processed analysis data as a text file."""
    if not SAVE_DATA:
        return

    ensure_output_dir()
    data_path = get_output_path("pipeline_data.txt")
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


def main() -> None:
    loadcell_adc = load_interleaved_channel(INPUT_FILE, LOADCELL_CHANNEL_INDEX)
    barometer_raw = load_interleaved_channel(INPUT_FILE, BAROMETER_CHANNEL_INDEX)
    time = np.arange(loadcell_adc.size) / SAMPLING_RATE

    raw_force = calibrated_force(loadcell_adc)
    raw_pressure = convert_to_pressure(barometer_raw)

    drift_result = apply_drift_correction(raw_force)
    modeled_drift = drift_result["modeled_drift"]
    corrected_force = drift_result["corrected_force"]
    filtered_force = zero_phase_lowpass(corrected_force, LOADCELL_LOWPASS_CUTOFF_HZ, LOADCELL_LOWPASS_ORDER)

    filtered_pressure = zero_phase_lowpass(raw_pressure, BAROMETER_LOWPASS_CUTOFF_HZ, BAROMETER_LOWPASS_ORDER)
    pressure_baseline = calculate_pressure_baseline(filtered_pressure)
    raw_gauge_pressure = raw_pressure - pressure_baseline
    filtered_gauge_pressure = filtered_pressure - pressure_baseline

    pressure_metrics = calculate_pressure_metrics(time, filtered_gauge_pressure)
    thrust_metrics = calculate_thrust_metrics(
        time,
        filtered_force,
        PROPELLANT_MASS,
    )

    save_report(thrust_metrics, pressure_metrics, drift_result, pressure_baseline)
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
        plot_loadcell_summary(time, corrected_force, filtered_force, thrust_metrics)
        plot_barometer_summary(time, raw_gauge_pressure, filtered_gauge_pressure, thrust_metrics, pressure_metrics)
        plot_combined_loadcell_barometer(
            time,
            corrected_force,
            filtered_force,
            raw_gauge_pressure,
            filtered_gauge_pressure,
            thrust_metrics,
            pressure_metrics,
        )
        plt.show()

    print_terminal_summary(thrust_metrics, pressure_metrics, drift_result, loadcell_adc.size, barometer_raw.size)


if __name__ == "__main__":
    main()
