import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker



def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    return (-28.5150 + 0.0397 * adc_value) * 9.80665+7



def load_odd_lines(file_path: str = "D:/tmstest1.txt") -> np.ndarray:
    """Load only the odd‑numbered lines (0‑based index) from a text file."""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    return np.array([
        float(lines[i].strip())
        for i in range(0, len(lines), 2)
        if lines[i].strip()
    ])


def save_calibrated_data(
    time_axis: np.ndarray,
    calibrated_force_values: np.ndarray,
    out_path: str = "D:/calibrated_loadcell.txt",
) -> None:
    """Save (t, F) pairs as a tab‑separated text file with a header."""
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
    sample_period = 414 / 200_000  # seconds per sample
    t = np.arange(raw_data.size) * sample_period
    force_N = calibrated_force(raw_data)


    impulse = np.trapz(force_N, dx=sample_period)
    print(f"Total impulse: {impulse:.3f} N·s")


    save_calibrated_data(t, force_N)

  
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1.plot(t, raw_data, color="gray")
    ax1.set_ylabel("ADC Raw Value")
    ax1.set_title("Raw Loadcell Data (Odd Lines Only)")
    ax1.grid(True)
    ax1.xaxis.set_major_locator(ticker.MultipleLocator(0.1))

    ax2.plot(t, force_N, color="blue")
    ax2.set_ylabel("Force (N)")
    ax2.set_xlabel("Time (s)")
    ax2.set_title("Calibrated Loadcell Output")
    ax2.grid(True)
    ax2.xaxis.set_major_locator(ticker.MultipleLocator(0.1))

    plt.tight_layout()
    plt.show()



if __name__ == "__main__":
    raw_adc = load_odd_lines()
    plot_raw_and_calibrated(raw_adc)