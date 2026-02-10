"""
TMS (Thrust Measurement System) Analysis Tool
Professional propulsion test data analysis following scholarly conventions

Essential outputs per AIAA/NASA standards:
- Thrust curve with raw/filtered overlay
- Calibration traceability (R², slope, intercept)
- Uncertainty quantification
- Performance metrics with error bounds
"""
import numpy as np
import matplotlib.pyplot as plt
import os
from typing import Dict, Tuple, Optional
from scipy.ndimage import uniform_filter1d

# ===== CONFIGURATION =====
INPUT_FILE = "Data/TMS_10.txt"
OUTPUT_DIR = "Data/analysis_output"

# Sampling rate
SAMPLING_RATE = 320  # samples per second (sps)

# Calibration coefficients (from load cell calibration)
CALIBRATION_SLOPE = -0.0389      # kg/ADC
CALIBRATION_INTERCEPT = -192.59  # kg
CALIBRATION_R_SQUARED = 0.9992   # R² from calibration fit
GRAVITATIONAL_CONSTANT = 9.80665 # m/s²
FORCE_OFFSET = 2.48              # N (baseline offset)

# Analysis parameters
BASELINE_SAMPLES = 100  # Pre-ignition samples for baseline
FILTER_WINDOW = 5       # Moving average window for filtered curve
PROPELLANT_MASS = None  # kg (set if known for Isp calculation)

# Uncertainty sources
CALIBRATION_UNCERTAINTY = 0.005  # 0.5% from R² residuals
ADC_QUANTIZATION = 1.0           # ADC counts (16-bit resolution)
TIMING_UNCERTAINTY = 1.0 / SAMPLING_RATE  # seconds

SAVE_PLOT = True
# =========================

# Motor classification (NAR/TRA impulse ranges in N·s)
MOTOR_CLASSES = [
    ('1/4A', 0, 0.625), ('1/2A', 0.626, 1.25), ('A', 1.26, 2.50),
    ('B', 2.51, 5.00), ('C', 5.01, 10.00), ('D', 10.01, 20.00),
    ('E', 20.01, 40.00), ('F', 40.01, 80.00), ('G', 80.01, 160.00),
    ('H', 160.01, 320.00), ('I', 320.01, 640.00), ('J', 640.01, 1280.00),
    ('K', 1280.01, 2560.00), ('L', 2560.01, 5120.00), ('M', 5120.01, 10240.00),
    ('N', 10240.01, 20480.00), ('O', 20480.01, 40960.00)
]


def calibrated_force(adc_value: float | np.ndarray) -> float | np.ndarray:
    """Convert ADC values to calibrated force (N)."""
    return (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc_value) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET


def load_data(file_path: str) -> Tuple[np.ndarray, np.ndarray]:
    """Load TMS data from file."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Load odd-indexed lines (0, 2, 4, ...)
    values = [float(lines[i].strip()) for i in range(0, len(lines), 2) if lines[i].strip()]
    
    raw_adc = np.array(values)
    time = np.arange(raw_adc.size) / SAMPLING_RATE
    
    return raw_adc, time


def filter_thrust(thrust: np.ndarray, window: int = FILTER_WINDOW) -> np.ndarray:
    """Apply moving average filter to thrust data."""
    return uniform_filter1d(thrust, size=window, mode='nearest')


def classify_motor(total_impulse: float) -> str:
    """Classify motor based on total impulse (NAR/TRA standard)."""
    for class_name, min_imp, max_imp in MOTOR_CLASSES:
        if min_imp <= total_impulse <= max_imp:
            return class_name
    if total_impulse > 40960:
        return ">O"
    return "<1/4A"


def estimate_uncertainty(thrust: np.ndarray, total_impulse: float, burn_time: float) -> Dict:
    """
    Estimate measurement uncertainty from calibration and sampling.
    
    Sources:
    - Calibration uncertainty (from R² residuals)
    - ADC quantization error
    - Integration error (numerical)
    """
    dt = 1.0 / SAMPLING_RATE
    
    # Force uncertainty from calibration
    force_uncertainty_pct = (1 - CALIBRATION_R_SQUARED) * 100  # % from R² residuals
    force_uncertainty_pct = max(force_uncertainty_pct, CALIBRATION_UNCERTAINTY * 100)
    
    # ADC quantization contribution to force
    adc_force_contribution = abs(CALIBRATION_SLOPE * ADC_QUANTIZATION * GRAVITATIONAL_CONSTANT)
    
    # Total impulse uncertainty (error propagation)
    # δI = sqrt((δF/F)² + (δt/t)²) × I
    relative_force_error = force_uncertainty_pct / 100
    relative_time_error = TIMING_UNCERTAINTY / burn_time if burn_time > 0 else 0
    
    impulse_uncertainty = total_impulse * np.sqrt(relative_force_error**2 + relative_time_error**2)
    
    # Peak thrust uncertainty
    peak_uncertainty = np.max(thrust) * relative_force_error
    
    return {
        'force_uncertainty_pct': force_uncertainty_pct,
        'adc_contribution': adc_force_contribution,
        'impulse_uncertainty': impulse_uncertainty,
        'peak_uncertainty': peak_uncertainty,
        'timing_uncertainty': TIMING_UNCERTAINTY * 1000,  # ms
    }


def calculate_metrics(
    time: np.ndarray, 
    thrust_raw: np.ndarray,
    thrust_filtered: np.ndarray,
    propellant_mass: Optional[float] = None
) -> Dict:
    """
    Calculate essential propulsion metrics following scholarly conventions.
    
    Uses filtered thrust for event detection, raw for display.
    """
    dt = time[1] - time[0] if len(time) > 1 else 1.0 / SAMPLING_RATE
    thrust = thrust_filtered  # Use filtered for calculations
    
    # Peak thrust
    peak_thrust = np.max(thrust)
    peak_idx = np.argmax(thrust)
    peak_time = time[peak_idx]
    
    # 10% threshold for burn time calculation (standard definition)
    threshold_10 = 0.10 * peak_thrust
    
    # Find ignition (first crossing of 10% threshold)
    above_threshold = thrust >= threshold_10
    if np.any(above_threshold):
        ignition_idx = np.where(above_threshold)[0][0]
        burnout_idx = np.where(above_threshold)[0][-1]
    else:
        ignition_idx = 0
        burnout_idx = len(thrust) - 1
    
    ignition_time = time[ignition_idx]
    burnout_time = time[burnout_idx]
    
    # Burn time (action time): 10% to 10%
    burn_time = burnout_time - ignition_time
    
    # Ignition delay (점화 지연): time from t=0 to ignition
    ignition_delay = ignition_time
    
    # Total impulse (integrate thrust over burn time)
    total_impulse = np.trapz(thrust[ignition_idx:burnout_idx+1], dx=dt)
    
    # Average thrust during burn
    avg_thrust = total_impulse / burn_time if burn_time > 0 else 0
    
    # Specific impulse (if propellant mass known)
    if propellant_mass is not None and propellant_mass > 0:
        specific_impulse = total_impulse / (propellant_mass * GRAVITATIONAL_CONSTANT)
    else:
        specific_impulse = None
    
    # Motor classification
    motor_class = classify_motor(total_impulse)
    motor_designation = f"{motor_class}{int(round(avg_thrust))}"
    
    # Uncertainty estimation
    uncertainty = estimate_uncertainty(thrust, total_impulse, burn_time)
    
    return {
        'peak_thrust': peak_thrust,
        'peak_time': peak_time,
        'total_impulse': total_impulse,
        'avg_thrust': avg_thrust,
        'burn_time': burn_time,
        'ignition_delay': ignition_delay,
        'ignition_time': ignition_time,
        'burnout_time': burnout_time,
        'motor_class': motor_class,
        'motor_designation': motor_designation,
        'specific_impulse': specific_impulse,
        'ignition_idx': ignition_idx,
        'burnout_idx': burnout_idx,
        'peak_idx': peak_idx,
        'uncertainty': uncertainty,
    }


def plot_thrust_curve(
    time: np.ndarray, 
    thrust_raw: np.ndarray, 
    thrust_filtered: np.ndarray,
    metrics: Dict
) -> None:
    """
    Create publication-quality thrust curve plot.
    Shows raw and filtered data overlay for data quality transparency.
    """
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Raw thrust curve (light, shows noise/fidelity)
    ax.plot(time, thrust_raw, color='lightgray', linewidth=0.5, alpha=0.7, label='Raw data')
    
    # Filtered thrust curve (primary)
    ax.plot(time, thrust_filtered, 'b-', linewidth=1.5, label='Filtered')
    
    # Zero baseline
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5, alpha=0.3)
    
    # 10% threshold line
    threshold_10 = 0.10 * metrics['peak_thrust']
    ax.axhline(y=threshold_10, color='gray', linestyle='--', linewidth=0.8, alpha=0.5, 
               label='10% threshold')
    
    # Event markers
    # Ignition point
    ax.axvline(x=metrics['ignition_time'], color='green', linestyle=':', linewidth=1.5, alpha=0.8)
    ax.plot(metrics['ignition_time'], thrust_filtered[metrics['ignition_idx']], 
            'g^', markersize=10, label='Ignition')
    
    # Peak thrust
    ax.plot(metrics['peak_time'], metrics['peak_thrust'], 'ro', markersize=12, 
            label=f'Peak: {metrics["peak_thrust"]:.1f} N')
    
    # Burnout point
    ax.axvline(x=metrics['burnout_time'], color='red', linestyle=':', linewidth=1.5, alpha=0.8)
    ax.plot(metrics['burnout_time'], thrust_filtered[metrics['burnout_idx']], 
            'rv', markersize=10, label='Burnout')
    
    # Fill area under curve (impulse visualization)
    ax.fill_between(time[metrics['ignition_idx']:metrics['burnout_idx']+1], 
                   thrust_filtered[metrics['ignition_idx']:metrics['burnout_idx']+1], 
                   0, alpha=0.15, color='blue')
    
    # Uncertainty band (±uncertainty around peak)
    unc = metrics['uncertainty']
    
    # Metrics annotation box
    isp_text = f"Specific Impulse: {metrics['specific_impulse']:.1f} s\n" if metrics['specific_impulse'] else ""
    metrics_text = (
        f"Motor: {metrics['motor_designation']}\n"
        f"───────────────────────\n"
        f"Peak Thrust:    {metrics['peak_thrust']:.2f} ± {unc['peak_uncertainty']:.2f} N\n"
        f"Total Impulse:  {metrics['total_impulse']:.2f} ± {unc['impulse_uncertainty']:.2f} N·s\n"
        f"Avg Thrust:     {metrics['avg_thrust']:.2f} N\n"
        f"Burn Time:      {metrics['burn_time']*1000:.1f} ms\n"
        f"Ignition Delay: {metrics['ignition_delay']*1000:.1f} ms\n"
        f"{isp_text}"
        f"───────────────────────\n"
        f"Calibration R²: {CALIBRATION_R_SQUARED:.4f}"
    )
    ax.text(0.98, 0.98, metrics_text, transform=ax.transAxes,
           verticalalignment='top', horizontalalignment='right',
           bbox=dict(boxstyle='round', facecolor='white', edgecolor='gray', alpha=0.95),
           fontsize=9, fontfamily='monospace')
    
    # Labels and title
    ax.set_xlabel('Time (s)', fontsize=12)
    ax.set_ylabel('Thrust (N)', fontsize=12)
    ax.set_title('Static Fire Test - Thrust Curve', fontsize=14, fontweight='bold')
    
    # Legend
    ax.legend(loc='upper left', fontsize=9)
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=min(0, np.min(thrust_raw)*1.1))
    
    plt.tight_layout()
    
    if SAVE_PLOT:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        plot_path = os.path.join(OUTPUT_DIR, "thrust_curve.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"Plot saved → {plot_path}")
    
    plt.show()


def save_report(metrics: Dict) -> None:
    """Save scholarly analysis report with calibration traceability."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    unc = metrics['uncertainty']
    
    report_path = os.path.join(OUTPUT_DIR, "test_report.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("═" * 60 + "\n")
        f.write("           STATIC FIRE TEST REPORT\n")
        f.write("═" * 60 + "\n\n")
        
        f.write(f"Motor Designation: {metrics['motor_designation']}\n")
        f.write(f"Motor Class: {metrics['motor_class']}\n\n")
        
        # Performance Metrics
        f.write("─" * 60 + "\n")
        f.write("PERFORMANCE METRICS\n")
        f.write("─" * 60 + "\n")
        f.write(f"Peak Thrust (F_max):      {metrics['peak_thrust']:>8.2f} ± {unc['peak_uncertainty']:.2f} N\n")
        f.write(f"Total Impulse (I_t):      {metrics['total_impulse']:>8.2f} ± {unc['impulse_uncertainty']:.2f} N·s\n")
        f.write(f"Average Thrust (F_avg):   {metrics['avg_thrust']:>8.2f} N\n")
        f.write(f"Burn Time (t_b):          {metrics['burn_time']*1000:>8.1f} ms\n")
        f.write(f"Ignition Delay (점화지연):  {metrics['ignition_delay']*1000:>8.1f} ms\n")
        
        if metrics['specific_impulse'] is not None:
            f.write(f"Specific Impulse (Isp):   {metrics['specific_impulse']:>8.1f} s\n")
        
        # Timing Details
        f.write("\n─" * 60 + "\n")
        f.write("TIMING\n")
        f.write("─" * 60 + "\n")
        f.write(f"Ignition Time:            {metrics['ignition_time']*1000:>8.1f} ms\n")
        f.write(f"Peak Time:                {metrics['peak_time']*1000:>8.1f} ms\n")
        f.write(f"Burnout Time:             {metrics['burnout_time']*1000:>8.1f} ms\n")
        
        # Calibration Traceability
        f.write("\n─" * 60 + "\n")
        f.write("CALIBRATION TRACEABILITY\n")
        f.write("─" * 60 + "\n")
        f.write(f"Load Cell Calibration R²: {CALIBRATION_R_SQUARED:.4f}\n")
        f.write(f"Calibration Slope:        {CALIBRATION_SLOPE:.6f} kg/ADC\n")
        f.write(f"Calibration Intercept:    {CALIBRATION_INTERCEPT:.4f} kg\n")
        f.write(f"Sampling Rate:            {SAMPLING_RATE} sps\n")
        
        # Uncertainty Budget
        f.write("\n─" * 60 + "\n")
        f.write("UNCERTAINTY BUDGET\n")
        f.write("─" * 60 + "\n")
        f.write(f"Force Uncertainty:        ±{unc['force_uncertainty_pct']:.2f}%\n")
        f.write(f"ADC Contribution:         ±{unc['adc_contribution']:.3f} N\n")
        f.write(f"Timing Uncertainty:       ±{unc['timing_uncertainty']:.2f} ms\n")
        f.write(f"Impulse Uncertainty:      ±{unc['impulse_uncertainty']:.2f} N·s\n")
        
        f.write("\n" + "═" * 60 + "\n")
    
    print(f"Report saved → {report_path}")


def print_summary(metrics: Dict) -> None:
    """Print essential metrics to console."""
    unc = metrics['uncertainty']
    
    print("\n" + "═" * 55)
    print("          STATIC FIRE TEST RESULTS")
    print("═" * 55)
    print(f"\n  Motor Designation: {metrics['motor_designation']}")
    print(f"\n  Peak Thrust:       {metrics['peak_thrust']:.2f} ± {unc['peak_uncertainty']:.2f} N")
    print(f"  Total Impulse:     {metrics['total_impulse']:.2f} ± {unc['impulse_uncertainty']:.2f} N·s")
    print(f"  Average Thrust:    {metrics['avg_thrust']:.2f} N")
    print(f"  Burn Time:         {metrics['burn_time']*1000:.1f} ms")
    print(f"  Ignition Delay:    {metrics['ignition_delay']*1000:.1f} ms (점화 지연)")
    
    if metrics['specific_impulse'] is not None:
        print(f"  Specific Impulse:  {metrics['specific_impulse']:.1f} s")
    
    print(f"\n  Calibration R²:    {CALIBRATION_R_SQUARED:.4f}")
    print("═" * 55 + "\n")


def main():
    """Main analysis workflow."""
    # Load data
    print("Loading data...")
    raw_adc, time = load_data(INPUT_FILE)
    print(f"✓ Loaded {len(raw_adc)} samples ({time[-1]:.2f} s)")
    
    # Calibrate
    force = calibrated_force(raw_adc)
    
    # Baseline correction
    baseline = np.mean(force[:BASELINE_SAMPLES])
    thrust_raw = force - baseline
    
    # Filter for calculations
    thrust_filtered = filter_thrust(thrust_raw, FILTER_WINDOW)
    
    # Calculate metrics
    print("Calculating metrics...")
    metrics = calculate_metrics(time, thrust_raw, thrust_filtered, PROPELLANT_MASS)
    
    # Print summary
    print_summary(metrics)
    
    # Plot (shows both raw and filtered)
    print("Generating plot...")
    plot_thrust_curve(time, thrust_raw, thrust_filtered, metrics)
    
    # Save report
    save_report(metrics)
    
    print("✓ Analysis complete!")


if __name__ == "__main__":
    main()
