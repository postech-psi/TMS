"""Joint thrust analysis for one firing split across two consecutive TMS recordings.

The firmware writes fixed-length files, so a late ignition can leave the burn running
into the next file with an unsampled interval between them. This script:

* aligns the second file on the first file's time axis using the device sampling-start
  uptime headers (microseconds since power-on, same power cycle required);
* uses the first file's pre-event loadcell baseline for both files;
* filters each file separately (no filtering across the gap);
* integrates the measured force above the fixed threshold and reports, separately,
  an estimate for the unsampled interval;
* cleans a drifting chamber-pressure channel (running median, then a smooth baseline
  through thrust-free periods) and checks whether the result tracks thrust;
* draws the session with the pipeline's standard loadcell, barometer and combined plots.

Gap model: earlier firings' thrust curves (--templates) are fitted to the force next
to the gap; the median accepted fill is the estimate. Fallback ("knee fit"): the end-of-file trend of the first recording (slope from a
least-squares line over EDGE_FIT_S) is continued until it meets the decay line
projected back from the start of the second recording; the corner is rounded with a
soft minimum. Both edge values are matched. A straight bridge and the range spanned
by the two boundary values are kept for comparison.

Measured and estimated quantities stay in separate fields. Nothing here recovers
the missing samples.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import median_filter
from scipy.optimize import least_squares

import tms_data_pipeline as tms


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    rec = tms.load_recording(path)
    rec["path"] = path
    rec["n"] = rec["loadcell_adc"].size
    return rec


EDGE_FIT_S = 0.1
SOFT_CORNER_N = 3.0
TEMPLATE_FIT_BEFORE_GAP_S = 1.0  # templates are fitted to the force next to the gap, not the rise
PRESSURE_DESPIKE_S = 0.1
PRESSURE_ANCHOR_BIN_S = 0.5
PRESSURE_BURN_MARGIN_S = (0.1, 0.3)
PRESSURE_MIN_THRUST_CORRELATION = 0.5


def edge_slope(values: np.ndarray, fs: int, at_end: bool) -> float:
    count = max(4, int(round(EDGE_FIT_S * fs)))
    segment = values[-count:] if at_end else values[:count]
    return float(np.polyfit(np.arange(segment.size) / fs, segment, 1)[0])


def knee_fit(tau: np.ndarray, gap: float, y0: float, s0: float, y1: float, s1: float) -> np.ndarray:
    """Soft minimum of the continued plateau trend and the back-projected decay."""
    plateau = y0 + s0 * tau
    decay = y1 + s1 * (tau - gap)
    k = SOFT_CORNER_N
    low = np.minimum(plateau, decay)
    return low - k * np.log(np.exp(-(plateau - low) / k) + np.exp(-(decay - low) / k))


def load_template(path: Path, threshold: float) -> dict | None:
    """Peak-normalized filtered thrust from an earlier pipeline TSV, time from threshold onset."""
    header = path.open(encoding="utf-8").readline().rstrip("\n").split("\t")
    if "filtered_force_N" not in header:
        return None
    data = np.genfromtxt(path, delimiter="\t", skip_header=1, usecols=(0, header.index("filtered_force_N")))
    time, force = data[:, 0], data[:, 1]
    peak = float(np.nanmax(force))
    above = np.flatnonzero(force >= threshold)
    if peak < 30 or not above.size:
        return None
    t0 = time[above[0]]
    return {"path": path, "time": time - t0, "shape": force / peak, "peak_n": peak}


def template_fill(template: dict, t_fit: np.ndarray, y_fit: np.ndarray, onset: float,
                  t_gap: np.ndarray, edges: tuple[float, float, float, float]) -> dict:
    """Fit amplitude, time shift and time stretch of a template; pin the fill to both gap edges."""
    def model(params, t):
        amp, shift, stretch = params
        return amp * np.interp((t - onset - shift) / stretch, template["time"], template["shape"], left=0.0, right=0.0)

    start = [float(np.max(y_fit)), 0.0, 1.0]
    fit = least_squares(lambda q: model(q, t_fit) - y_fit, start,
                        bounds=([0.5 * start[0], -2.0, 0.5], [1.5 * start[0], 2.0, 2.0]))
    rmse = float(np.sqrt(np.mean(fit.fun ** 2)))
    ta, ya, tb, yb = edges
    raw = model(fit.x, t_gap)
    ea = ya - model(fit.x, np.array([ta]))[0]
    eb = yb - model(fit.x, np.array([tb]))[0]
    weight = (t_gap - ta) / (tb - ta)
    return {"template": template["path"].as_posix(), "amplitude_n": float(fit.x[0]), "shift_s": float(fit.x[1]),
            "stretch": float(fit.x[2]), "rmse_n": rmse, "edge_correction_n": [float(ea), float(eb)],
            "fill": raw + ea * (1 - weight) + eb * weight}


def crossings(signal: np.ndarray, threshold: float) -> np.ndarray:
    return np.flatnonzero(signal >= threshold)


def analyze(first_path: Path, second_path: Path, output_dir: Path, prefix: str, dpi: int,
            template_paths: list[Path] | None = None, max_template_rmse: float = 6.0) -> dict:
    a, b = load(first_path), load(second_path)
    if a["power_on_us"] != b["power_on_us"]:
        raise ValueError("Recordings come from different power cycles; header alignment is invalid")
    if b["sampling_start_us"] <= a["sampling_start_us"]:
        raise ValueError("Second recording must start after the first")

    fs = tms.SAMPLING_RATE
    threshold = tms.THRUST_EVENT_THRESHOLD_N
    offset_s = (b["sampling_start_us"] - a["sampling_start_us"]) / 1e6
    t_a = np.arange(a["n"]) / fs
    t_b = offset_s + np.arange(b["n"]) / fs
    gap_s = float(t_b[0] - t_a[-1])

    raw_a, raw_b = tms.calibrated_force(a["loadcell_adc"]), tms.calibrated_force(b["loadcell_adc"])
    baseline = tms.calculate_horizontal_offset(raw_a)
    offset_n = float(baseline["offset_force"])
    f_a = tms.zero_phase_lowpass(raw_a - offset_n, tms.LOADCELL_LOWPASS_CUTOFF_HZ, tms.LOADCELL_LOWPASS_ORDER)
    f_b = tms.zero_phase_lowpass(raw_b - offset_n, tms.LOADCELL_LOWPASS_CUTOFF_HZ, tms.LOADCELL_LOWPASS_ORDER)

    above_a, above_b = crossings(f_a, threshold), crossings(f_b, threshold)
    if not above_a.size:
        raise ValueError("No threshold crossing in the first recording")
    onset_idx = int(above_a[0])
    first_ends_above = bool(f_a[-1] >= threshold)
    second_starts_above = bool(f_b[0] >= threshold)
    end_idx = int(above_b[-1]) if above_b.size else None
    tail_b = f_b[-fs:]
    dt = 1.0 / fs

    measured_a = float(np.trapezoid(f_a[onset_idx:], dx=dt))
    measured_b = float(np.trapezoid(f_b[:end_idx + 1], dx=dt)) if end_idx is not None else 0.0
    boundary = (float(f_a[-1]), float(f_b[0]))
    bridge_linear = 0.5 * (boundary[0] + boundary[1]) * gap_s
    bridge_range = (min(boundary) * gap_s, max(boundary) * gap_s)
    measured_total = measured_a + measured_b
    end_time = float(t_b[end_idx]) if end_idx is not None else None
    duration = end_time - float(t_a[onset_idx]) if end_time is not None else None
    slope_a, slope_b = edge_slope(f_a, fs, True), edge_slope(f_b, fs, False)
    tau = np.arange(1, int(np.floor(gap_s * fs)) + 1) / fs
    tau = tau[tau < gap_s]
    t_gap = t_a[-1] + tau
    f_gap = knee_fit(tau, gap_s, boundary[0], slope_a, boundary[1], slope_b)
    gap_x = np.concatenate(([0.0], tau, [gap_s]))
    gap_y = np.concatenate(([boundary[0]], f_gap, [boundary[1]]))
    bridge_fit = float(np.trapezoid(gap_y, gap_x))
    if slope_b < 0 and slope_a > slope_b:
        knee_s = float((boundary[1] - slope_b * gap_s - boundary[0]) / (slope_a - slope_b))
    else:
        knee_s = None
    knee_total = measured_total + bridge_fit
    templates = []
    fit_mask_a = t_a >= max(float(t_a[onset_idx]), float(t_a[-1]) - TEMPLATE_FIT_BEFORE_GAP_S)
    last_b = end_idx if end_idx is not None else f_b.size - 1
    fit_mask_b = np.arange(f_b.size) <= last_b
    t_fit = np.concatenate((t_a[fit_mask_a], t_b[fit_mask_b]))
    y_fit = np.concatenate((f_a[fit_mask_a], f_b[fit_mask_b]))
    for path in template_paths or []:
        tpl = load_template(Path(path), threshold)
        if tpl is None:
            continue
        res = template_fill(tpl, t_fit, y_fit, float(t_a[onset_idx]), gap_x + t_a[-1],
                            (float(t_a[-1]), boundary[0], float(t_b[0]), boundary[1]))
        res["gap_impulse_n_s"] = float(np.trapezoid(res["fill"], gap_x))
        res["gap_max_n"] = float(np.max(res["fill"]))
        res["accepted"] = res["rmse_n"] <= max_template_rmse
        templates.append(res)
    accepted = [r for r in templates if r["accepted"]]
    if accepted:
        fills = np.array([r["fill"] for r in accepted])
        gap_center = np.median(fills, axis=0)
        gap_lo, gap_hi = fills.min(axis=0), fills.max(axis=0)
        gap_method = "historical_template_median"
        gap_impulse = float(np.trapezoid(gap_center, gap_x))
        gap_impulse_range = (min(r["gap_impulse_n_s"] for r in accepted), max(r["gap_impulse_n_s"] for r in accepted))
    else:
        gap_center, gap_lo, gap_hi = gap_y, gap_y, gap_y
        gap_method = "knee_fit"
        gap_impulse, gap_impulse_range = bridge_fit, bridge_range
    estimate_total = measured_total + gap_impulse

    peak_a_idx = int(np.argmax(f_a))
    peak_b_idx = int(np.argmax(f_b))
    peak_n = float(max(f_a[peak_a_idx], f_b[peak_b_idx]))
    peak_s = float(t_a[peak_a_idx] if f_a[peak_a_idx] >= f_b[peak_b_idx] else t_b[peak_b_idx])

    # Pressure: chamber sensor with a drifting offset (user-confirmed placement).
    n_a = t_a.size
    t_ab = np.concatenate((t_a, t_b))
    adc_ab = np.concatenate((a["pressure_adc"], b["pressure_adc"]))
    pressure = clean_pressure(t_ab, adc_ab, float(t_a[onset_idx]), end_time if end_time is not None else float(t_b[-1]), fs)
    corrected_p = pressure["corrected_bar"]
    burn_ab = np.concatenate((t_a >= t_a[onset_idx], np.arange(f_b.size) <= last_b))
    force_ab = np.concatenate((f_a, f_b))
    correlation = float(np.corrcoef(force_ab[burn_ab], corrected_p[burn_ab])[0, 1])
    quiet_noise = float(np.std(corrected_p[pressure["quiet_mask"]]))
    p_peak_idx = int(np.argmax(np.where(burn_ab, corrected_p, -np.inf)))
    pressure_status = "unverified_does_not_track_thrust" if correlation < PRESSURE_MIN_THRUST_CORRELATION else "drift_corrected"

    def stats(rec, f):
        q = int(0.25 * fs)
        return {
            "file": rec["path"].name, "sha256": sha256(rec["path"]), "bytes": rec["path"].stat().st_size,
            "sampling_start_us": rec["sampling_start_us"], "power_on_us": rec["power_on_us"], "sample_pairs": rec["n"],
            "loadcell_adc_first_quarter_second_median": float(np.median(rec["loadcell_adc"][:q])),
            "loadcell_adc_last_quarter_second_median": float(np.median(rec["loadcell_adc"][-q:])),
            "filtered_force_first_n": float(f[0]), "filtered_force_last_n": float(f[-1]),
            "pressure_adc_first": float(rec["pressure_adc"][0]), "pressure_adc_last": float(rec["pressure_adc"][-1]),
        }

    total_range = [measured_total + gap_impulse_range[0], measured_total + gap_impulse_range[1]]
    result = {
        "method": {
            "script": "Calibration/tms_split_recording.py",
            "script_sha256": sha256(Path(__file__)),
            "pipeline_sha256": sha256(Path(tms.__file__)),
            "pipeline_revision": tms.pipeline_revision(),
            "threshold_n": threshold,
            "sampling_rate_hz_assumed": fs,
            "alignment": "Second file placed at the difference of the sampling-start uptime headers; both files use 320 Hz local axes.",
            "baseline": "First file's pre-event raw-force mean (pipeline horizontal offset), applied to both files.",
            "filtering": "Each file filtered separately; the only values inside the unsampled interval are the stated gap estimate.",
        },
        "recordings": [stats(a, f_a), stats(b, f_b)],
        "timing": {
            "second_file_offset_s": offset_s,
            "first_file_last_sample_s": float(t_a[-1]),
            "unsampled_interval_s": gap_s,
            "note": "If the real sample rate is below 320 Hz the files span more time and the true gap is shorter.",
        },
        "baseline": {
            "loadcell_offset_n": offset_n,
            "baseline_window_end_s": float(baseline["averaging_end_time_s"]),
            "return_to_baseline_n": float(np.mean(tail_b)),
            "return_to_baseline_std_n": float(np.std(tail_b)),
        },
        "measured": {
            "onset_s": float(t_a[onset_idx]),
            "first_file_ends_above_threshold": first_ends_above,
            "second_file_starts_above_threshold": second_starts_above,
            "end_s": end_time,
            "peak_n": peak_n,
            "peak_s": peak_s,
            "boundary_force_n": {"first_file_last": boundary[0], "second_file_first": boundary[1]},
            "impulse_first_file_n_s": measured_a,
            "impulse_second_file_n_s": measured_b,
            "impulse_measured_n_s": measured_total,
        },
        "estimated": {
            "gap_model": gap_method,
            "gap_impulse_n_s": gap_impulse,
            "gap_impulse_template_range_n_s": list(gap_impulse_range),
            "gap_max_n": float(np.max(gap_center)),
            "template_fit_window_before_gap_s": TEMPLATE_FIT_BEFORE_GAP_S,
            "template_acceptance_rmse_n": max_template_rmse,
            "templates": [{k: v for k, v in r.items() if k != "fill"} for r in templates],
            "knee_fit": {"edge_fit_window_s": EDGE_FIT_S, "edge_slope_first_file_end_n_per_s": slope_a,
                         "edge_slope_second_file_start_n_per_s": slope_b, "knee_after_gap_start_s": knee_s,
                         "gap_impulse_n_s": bridge_fit, "gap_max_n": float(gap_y.max()), "total_impulse_n_s": knee_total},
            "straight_bridge_gap_impulse_n_s": bridge_linear,
            "boundary_value_gap_impulse_range_n_s": list(bridge_range),
            "total_impulse_n_s": estimate_total,
            "total_impulse_range_n_s": total_range,
            "burn_duration_s": duration,
            "average_thrust_n": estimate_total / duration if duration else None,
            "assumption": ("Earlier firings' peak-normalized thrust curves are fitted (amplitude, time shift, time stretch) "
                           "to the force next to the gap and pinned to both gap edges; the median accepted fill is the central "
                           "value and the spread across accepted templates is the range. The knee fit (first file's end trend "
                           "continued until it meets the second file's initial decay) and a straight bridge are kept for "
                           "comparison. Measured impulse alone is a lower bound for non-negative thrust."),
        },
        "pressure": {
            "status": pressure_status,
            "sensor_placement": "Chamber (user-confirmed). The 6.4 s offset step and post-burn level are treated as sensor drift.",
            "method": (f"{PRESSURE_DESPIKE_S:.2f} s running median on raw ADC, inherited conversion, then a PCHIP baseline through "
                       f"{PRESSURE_ANCHOR_BIN_S:.1f} s medians of thrust-free periods (zero gauge pressure assumed there) is subtracted."),
            "anchor_count": len(pressure["anchors_s"]),
            "quiet_period_residual_std_bar": quiet_noise,
            "thrust_correlation_during_burn": correlation,
            "minimum_correlation_for_use": PRESSURE_MIN_THRUST_CORRELATION,
            "corrected_peak_bar": float(corrected_p[p_peak_idx]),
            "corrected_peak_s": float(t_ab[p_peak_idx]),
            "force_at_corrected_peak_n": float(force_ab[p_peak_idx]),
            "note": ("After drift removal the in-burn signal peaks before thrust reaches its plateau and then falls while thrust "
                     "is still rising; chamber pressure cannot do that. Values are retained for diagnosis, not as chamber pressure."
                     if pressure_status != "drift_corrected" else "Drift-corrected gauge pressure."),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    t_fill = t_a[-1] + gap_x[1:-1]
    nan_fill = np.full(t_fill.size, np.nan)
    p_raw_bar = tms.convert_to_pressure(adc_ab)
    stitched = {
        "time": np.concatenate((t_a, t_fill, t_b)),
        "raw_force": np.concatenate((raw_a, nan_fill, raw_b)),
        "drift_model": np.concatenate((np.full(n_a, offset_n), nan_fill, np.full(t_b.size, offset_n))),
        "measured_filtered": np.concatenate((f_a, nan_fill, f_b)),
        "loadcell_adc": np.concatenate((a["loadcell_adc"], nan_fill, b["loadcell_adc"])),
        "pressure_adc": np.concatenate((a["pressure_adc"], nan_fill, b["pressure_adc"])),
        "source": [a["path"].name] * n_a + ["gap_fit"] * t_fill.size + [b["path"].name] * t_b.size,
        "corrected": np.concatenate((raw_a - offset_n, nan_fill, raw_b - offset_n)),
        "filtered": np.concatenate((f_a, gap_center[1:-1], f_b)),
        "gap_low": np.concatenate((np.full(n_a, np.nan), gap_lo[1:-1], np.full(t_b.size, np.nan))),
        "gap_high": np.concatenate((np.full(n_a, np.nan), gap_hi[1:-1], np.full(t_b.size, np.nan))),
        "pressure_raw": np.concatenate((p_raw_bar[:n_a], nan_fill, p_raw_bar[n_a:])),
        "pressure_baseline": np.concatenate((pressure["baseline_bar"][:n_a], nan_fill, pressure["baseline_bar"][n_a:])),
        "pressure_corrected": np.concatenate((corrected_p[:n_a], nan_fill, corrected_p[n_a:])),
    }
    figures = standard_plots(stitched, a, b, t_a, t_b, gap_x, gap_center, gap_lo, gap_hi, len(accepted), result,
                             onset_idx, n_a + t_fill.size + last_b, output_dir, prefix, dpi)
    result["figures"] = figures
    result["series"] = f"{prefix}_pipeline_data.txt"
    # Pipeline TSV layout: filtered_force_N stays measured-only (nan in the gap);
    # analysis_force_N carries the measured force plus the fitted gap.
    raw_gauge = stitched["pressure_raw"] - stitched["pressure_baseline"]
    columns = [
        ("time_s", stitched["time"], "{:.6f}"),
        ("raw_force_N", stitched["raw_force"], "{:.6f}"),
        ("drift_model_N", stitched["drift_model"], "{:.6f}"),
        ("corrected_force_N", stitched["corrected"], "{:.6f}"),
        ("filtered_force_N", stitched["measured_filtered"], "{:.6f}"),
        ("raw_gauge_pressure", raw_gauge, "{:.6f}"),
        ("filtered_gauge_pressure", stitched["pressure_corrected"], "{:.6f}"),
        ("loadcell_adc", stitched["loadcell_adc"], "{:.0f}"),
        ("pressure_adc", stitched["pressure_adc"], "{:.0f}"),
        ("analysis_force_N", stitched["filtered"], "{:.6f}"),
        ("gap_fit_low_N", stitched["gap_low"], "{:.6f}"),
        ("gap_fit_high_N", stitched["gap_high"], "{:.6f}"),
        ("pressure_drift_baseline_bar", stitched["pressure_baseline"], "{:.6f}"),
    ]
    rows = ["\t".join([name for name, _, _ in columns] + ["source"])]
    for i in range(stitched["time"].size):
        cells = ["nan" if not np.isfinite(values[i]) else fmt.format(values[i]) for _, values, fmt in columns]
        rows.append("\t".join(cells + [stitched["source"][i]]))
    (output_dir / result["series"]).write_text("\n".join(rows) + "\n", encoding="utf-8")
    result["report"] = f"{prefix}_executive_report.txt"
    write_report(output_dir / result["report"], result, a, b)
    (output_dir / f"{prefix}_joint.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def write_report(path: Path, r: dict, a: dict, b: dict) -> None:
    """Executive report in the pipeline's format, separating measured and fitted values."""
    m, e, p, t, base = r["measured"], r["estimated"], r["pressure"], r["timing"], r["baseline"]
    accepted = [x for x in e["templates"] if x["accepted"]]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"{tms.REPORT_RULE}\nSTATIC FIRE REPORT - BURN SPLIT ACROSS TWO RECORDINGS\n{tms.REPORT_RULE}\n\n")
        f.write(f"Input files: {tms.format_project_relative_path(a['path'])} + {tms.format_project_relative_path(b['path'])}\n")
        f.write(f"Sampling rate: {tms.SAMPLING_RATE} sps\n\n")
        tms.write_report_section(f, "DATA QUALITY", [
            f"Thrust status: measured with a fitted unsampled interval ({e['gap_model']})",
            f"Pressure status: {p['status']}",
            "Time axis assumes uniform 320 Hz sampling; no per-sample timestamps are logged.",
            f"Second file aligned by sampling-start headers: offset {t['second_file_offset_s']:.6f} s.",
            f"Unsampled interval: {t['first_file_last_sample_s']:.6f} to {t['second_file_offset_s']:.6f} s ({t['unsampled_interval_s']:.6f} s).",
            "Ignition delay is time from the first recording's start, not an independently logged fire command.",
            "Calibration is inherited from the existing pipeline; no same-day calibration was supplied.",
        ])
        tms.write_report_section(f, "THRUST METRICS", [
            f"Ignition delay: {m['onset_s'] * 1000:.1f} ms",
            f"Peak thrust (measured): {m['peak_n']:.2f} N at {m['peak_s']:.6f} s",
            f"Total impulse (estimated): {e['total_impulse_n_s']:.2f} N s (range {e['total_impulse_range_n_s'][0]:.2f}-{e['total_impulse_range_n_s'][1]:.2f})",
            f"  Measured: {m['impulse_measured_n_s']:.2f} N s (first file {m['impulse_first_file_n_s']:.2f}, second file {m['impulse_second_file_n_s']:.2f})",
            f"  Fitted interval: {e['gap_impulse_n_s']:.2f} N s (range {e['gap_impulse_template_range_n_s'][0]:.2f}-{e['gap_impulse_template_range_n_s'][1]:.2f})",
            f"Average thrust (estimated): {e['average_thrust_n']:.2f} N",
            f"Burn duration: {e['burn_duration_s'] * 1000:.1f} ms ({m['onset_s']:.6f} to {m['end_s']:.6f} s)",
        ])
        tms.write_report_section(f, "UNSAMPLED INTERVAL FIT", [
            f"Templates: earlier firings fitted to the last {e['template_fit_window_before_gap_s']:.1f} s before the gap and the measured decay; pinned to both edges.",
            f"Edge force: {m['boundary_force_n']['first_file_last']:.2f} N / {m['boundary_force_n']['second_file_first']:.2f} N",
            f"Accepted (RMS <= {e['template_acceptance_rmse_n']:.1f} N): " + ", ".join(
                f"{Path(x['template']).parts[2]} ({x['rmse_n']:.2f} N)" for x in accepted),
            "Rejected: " + ", ".join(
                f"{Path(x['template']).parts[2]} ({x['rmse_n']:.2f} N)" for x in e["templates"] if not x["accepted"]),
            f"Knee-fit cross-check total: {e['knee_fit']['total_impulse_n_s']:.2f} N s; straight-bridge gap impulse: {e['straight_bridge_gap_impulse_n_s']:.2f} N s",
            "Measured impulse alone is a lower bound for non-negative thrust.",
        ])
        tms.write_report_section(f, "PRESSURE METRICS", [
            f"Drift-corrected peak: {p['corrected_peak_bar']:.3f} bar at {p['corrected_peak_s']:.6f} s (thrust {p['force_at_corrected_peak_n']:.1f} N)",
            f"Correlation with thrust during burn: r = {p['thrust_correlation_during_burn']:.2f} (minimum for use {p['minimum_correlation_for_use']:.2f})",
            f"Thrust-free residual: {p['quiet_period_residual_std_bar']:.3f} bar RMS",
            p["note"],
        ])
        tms.write_report_section(f, "CALIBRATION", [
            f"Loadcell calibration slope: {tms.CALIBRATION_SLOPE:.6f} kg/ADC",
            f"Loadcell calibration intercept: {tms.CALIBRATION_INTERCEPT:.4f} kg",
            f"Loadcell calibration R^2: {tms.CALIBRATION_R_SQUARED:.6f}",
            f"Pressure conversion: y = {tms.PRESSURE_SLOPE}x {tms.PRESSURE_INTERCEPT}",
        ])
        tms.write_report_section(f, "DATA PROCESSING", [
            f"Loadcell threshold (fixed absolute): {r['method']['threshold_n']:.2f} N",
            f"Loadcell baseline offset: {base['loadcell_offset_n']:.6f} N (first file, up to {base['baseline_window_end_s']:.6f} s), applied to both files",
            f"Return to baseline in second file: {base['return_to_baseline_n']:.3f} +/- {base['return_to_baseline_std_n']:.3f} N",
            f"Loadcell filter: Butterworth low-pass {tms.LOADCELL_LOWPASS_CUTOFF_HZ:.1f} Hz, order {tms.LOADCELL_LOWPASS_ORDER}; each file separately",
            "Pressure: " + p["method"],
            "filtered_force_N is measured only (nan in the gap); analysis_force_N includes the fitted interval.",
        ])
        f.write(f"{tms.REPORT_RULE}\n")


def clean_pressure(time: np.ndarray, adc: np.ndarray, onset: float, end: float, fs: int) -> dict:
    """Despike, then subtract a smooth baseline fitted through thrust-free periods."""
    window = int(PRESSURE_DESPIKE_S * fs) | 1
    despiked = tms.convert_to_pressure(median_filter(adc, size=window, mode="nearest"))
    quiet = (time < onset - PRESSURE_BURN_MARGIN_S[0]) | (time > end + PRESSURE_BURN_MARGIN_S[1])
    edges = np.arange(time[0], time[-1] + PRESSURE_ANCHOR_BIN_S, PRESSURE_ANCHOR_BIN_S)
    anchors_s, anchors_bar = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = quiet & (time >= lo) & (time < hi)
        if mask.sum() >= 0.4 * PRESSURE_ANCHOR_BIN_S * fs:
            anchors_s.append(float(time[mask].mean()))
            anchors_bar.append(float(np.median(despiked[mask])))
    baseline = PchipInterpolator(anchors_s, anchors_bar, extrapolate=True)(time)
    return {"despiked_bar": despiked, "baseline_bar": baseline, "corrected_bar": despiked - baseline,
            "quiet_mask": quiet, "anchors_s": anchors_s, "anchors_bar": anchors_bar}


def standard_plots(s: dict, a: dict, b: dict, t_a, t_b, gap_x, gap_center, gap_lo, gap_hi, template_count: int,
                   result: dict, ignition_idx: int, burnout_idx: int, output_dir: Path, prefix: str, dpi: int) -> list[str]:
    """Draw the session with the pipeline's own loadcell, barometer and combined figures."""
    measured, estimated, pressure = result["measured"], result["estimated"], result["pressure"]
    thrust_metrics = {
        "peak_thrust": measured["peak_n"], "peak_time": measured["peak_s"],
        "ignition_idx": ignition_idx, "ignition_time": measured["onset_s"],
        "burnout_idx": burnout_idx, "burnout_time": measured["end_s"],
        "burn_time": estimated["burn_duration_s"], "ignition_delay": measured["onset_s"],
        "total_impulse": estimated["total_impulse_n_s"], "threshold_force": result["method"]["threshold_n"],
    }
    pressure_metrics = {"peak_pressure": pressure["corrected_peak_bar"], "peak_pressure_time": pressure["corrected_peak_s"]}
    saved = {k: getattr(tms, k) for k in ("INPUT_FILENAME", "OUTPUT_DIR", "OUTPUT_PREFIX", "PLOT_DPI", "SAVE_PLOT",
                                          "PRESSURE_RAW_LABEL", "PRESSURE_FILTERED_LABEL", "PRESSURE_PEAK_LABEL",
                                          "FORCE_FILTERED_LABEL", "save_current_figure")}
    gap_start, gap_end = float(t_a[-1]), float(t_b[0])
    unverified = pressure["status"] != "drift_corrected"

    def decorate_and_save(filename: str) -> None:
        for ax in plt.gcf().axes:
            label = ax.get_ylabel()
            if not label or ax.get_legend() is None and not label.startswith("Force"):
                continue
            extra = []
            ax.axvspan(gap_start, gap_end, facecolor="none", edgecolor=tms.BURNOUT_MARK_COLOR, hatch="///", lw=0, alpha=0.55)
            if label.startswith("Force"):
                extra.append(ax.fill_between(gap_start + gap_x, gap_lo, gap_hi, color="#E0A890", alpha=0.55, lw=0,
                                             label=f"Gap fit range ({template_count} past firings)"))
                extra.append(ax.plot(gap_start + gap_x, gap_center, color="#C0502E", ls="--", lw=2.0,
                                     label="Fitted unsampled interval")[0])
                ax.text(0.01, 0.80 if filename.startswith("combined") else 0.84,
                        f"Unsampled {gap_start:.3f}-{gap_end:.3f} s filled from past thrust curves\n"
                        f"Impulse: {measured['impulse_measured_n_s']:.1f} N s measured + {estimated['gap_impulse_n_s']:.1f} N s fitted "
                        f"(total {estimated['total_impulse_range_n_s'][0]:.0f}-{estimated['total_impulse_range_n_s'][1]:.0f} N s)\n"
                        f"Average thrust: {estimated['average_thrust_n']:.1f} N",
                        transform=ax.transAxes, ha="left", va="top", fontsize=8.5,
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.95))
            elif unverified and filename.startswith("barometer"):
                ax.text(0.98, 0.97,
                        f"Drift-corrected chamber channel - unverified\n"
                        f"Correlation with thrust during burn: r = {pressure['thrust_correlation_during_burn']:.2f}\n"
                        f"Thrust-free residual: {pressure['quiet_period_residual_std_bar']:.1f} bar RMS",
                        transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#8A3B2E",
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="#8A3B2E", alpha=0.95))
            legend = ax.get_legend()
            if legend is not None and extra:
                handles = list(legend.legend_handles) + extra
                labels = [text.get_text() for text in legend.texts] + [h.get_label() for h in extra]
                ax.legend(handles, labels, loc="upper left", fontsize=8, ncol=2, framealpha=0.92)
        saved["save_current_figure"](filename)

    try:
        tms.INPUT_FILENAME = f"{a['path'].name} + {b['path'].name}"
        tms.OUTPUT_DIR, tms.OUTPUT_PREFIX, tms.PLOT_DPI, tms.SAVE_PLOT = output_dir, prefix, dpi, True
        tms.FORCE_FILTERED_LABEL = "Filtered corrected force"
        if unverified:
            tms.PRESSURE_RAW_LABEL = "Raw pressure, drift removed (unverified)"
            tms.PRESSURE_FILTERED_LABEL = "Despiked + drift-corrected pressure (unverified)"
            tms.PRESSURE_PEAK_LABEL = "Peak (unverified)"
        tms.save_current_figure = decorate_and_save
        raw_gauge = s["pressure_raw"] - s["pressure_baseline"]
        tms.plot_loadcell_summary(s["time"], s["corrected"], s["filtered"], thrust_metrics)
        tms.plot_barometer_summary(s["time"], raw_gauge, s["pressure_corrected"], thrust_metrics, pressure_metrics)
        tms.plot_combined_loadcell_barometer(s["time"], s["corrected"], s["filtered"], raw_gauge, s["pressure_corrected"],
                                             thrust_metrics, pressure_metrics)
    finally:
        for key, value in saved.items():
            setattr(tms, key, value)
        plt.close("all")
    return [f"{prefix}_{kind}_plot.png" for kind in ("loadcell", "barometer", "combined")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--templates", nargs="*", type=Path, default=[],
                        help="Earlier *_pipeline_data.txt files whose thrust shape informs the gap fill")
    parser.add_argument("--max-template-rmse", type=float, default=6.0)
    args = parser.parse_args()
    out = args.output_dir or args.first.parent / tms.OUTPUT_FOLDER_NAME
    result = analyze(args.first.resolve(), args.second.resolve(), out.resolve(), args.prefix, args.dpi,
                     list(args.templates), args.max_template_rmse)
    summary = {k: result[k] for k in ("timing", "measured", "pressure")}
    summary["estimated"] = {k: v for k, v in result["estimated"].items() if k != "templates"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
