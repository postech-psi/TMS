"""
TMS Data Calibration and Visualization Script
Converts raw ADC values to calibrated force measurements
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os

# Configuration - modify these as needed
INPUT_FILE = "Data/11_27/tms_data.txt"
OUTPUT_FILE = "Data/11_27/calibrated_loadcell_test.txt"

# Sampling rate
SAMPLING_RATE = 320  # samples per second (sps) 

# Calibration coefficients (from 6_16 dataset)
CALIBRATION_SLOPE = -0.0389
CALIBRATION_INTERCEPT = -192.59
GRAVITATIONAL_CONSTANT = 9.80665  # m/s²
FORCE_OFFSET = 2.48  # Additional offset in Newtons


def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    """Convert ADC raw values to calibrated force in Newtons."""
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def load_odd_lines(file_path: str) -> np.ndarray:
    """Load only the odd‑numbered lines (0‑based index) from a text file."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    values = [
        float(lines[i].strip())
        for i in range(0, len(lines), 2)
        if lines[i].strip()
    ]
    
    return np.array(values)


def save_calibrated_data(
    time_axis: np.ndarray,
    calibrated_force_values: np.ndarray,
    out_path: str,
) -> None:
    """Save (t, F) pairs as a tab‑separated text file with a header."""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    
    np.savetxt(
        out_path,
        np.column_stack((time_axis, calibrated_force_values)),
        delimiter="\t",
        header="time_s\tforce_N",
        comments="",
        fmt="%.6f",
    )
    print(f"Calibrated data saved → {out_path}")


def plot_raw_and_calibrated(raw_data: np.ndarray) -> None:
    """Plot raw ADC data and calibrated force; compute impulse & save output."""
    sample_period = 1.0 / SAMPLING_RATE  # seconds per sample
    
    t = np.arange(raw_data.size) * sample_period
    force_N = calibrated_force(raw_data)
    
    impulse = np.trapz(force_N, dx=sample_period)
    print(f"Total impulse: {impulse:.3f} N·s")
    print(f"Total samples: {len(raw_data)} at {SAMPLING_RATE} sps")
    
    save_calibrated_data(t, force_N, OUTPUT_FILE)
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    ax1.plot(t, raw_data, color="gray")
    ax1.set_ylabel("ADC Raw Value")
    ax1.set_title("Raw Loadcell Data (Odd Lines Only)")
    ax1.grid(True)
    ax1.xaxis.set_major_locator(ticker.MultipleLocator(0.1))
    
    ax2.plot(t, force_N, color="blue")
    ax2.set_ylabel("Force (N)")
    ax2.set_xlabel("Time (s)")
    ax2.set_title("Calibrated Loadcell Output")
    ax2.grid(True)
    ax2.xaxis.set_major_locator(ticker.MultipleLocator(0.1))
    
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    raw_adc = load_odd_lines(INPUT_FILE)
    plot_raw_and_calibrated(raw_adc)
