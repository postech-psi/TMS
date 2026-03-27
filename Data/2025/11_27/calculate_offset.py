"""
Calculate force offset from calibrated data
Offset = baseline value when no load is applied
"""
import numpy as np

# Configuration
input_file = '/Users/leetaeho/TMS/Data/11_27/calibrated_loadcell_test.txt'

# Load data (skip header)
data = np.loadtxt(input_file, skiprows=1)
time = data[:, 0]
force = data[:, 1]

# Calculate offset statistics
mean_offset = np.mean(force)
median_offset = np.median(force)
std_offset = np.std(force)
min_force = np.min(force)
max_force = np.max(force)

# Calculate offset using first N samples (assuming no load at start)
initial_samples = min(100, len(force))
initial_mean = np.mean(force[:initial_samples])
initial_std = np.std(force[:initial_samples])

print("="*60)
print("FORCE OFFSET CALCULATION")
print("="*60)
print(f"\nTotal data points: {len(force)}")
print(f"Time range: {time[0]:.6f} - {time[-1]:.6f} seconds")
print(f"Duration: {time[-1] - time[0]:.3f} seconds")

print("\n" + "-"*60)
print("OFFSET STATISTICS (All Data):")
print("-"*60)
print(f"Mean offset:     {mean_offset:.6f} N")
print(f"Median offset:   {median_offset:.6f} N")
print(f"Std deviation:   {std_offset:.6f} N")
print(f"Min force:       {min_force:.6f} N")
print(f"Max force:       {max_force:.6f} N")
print(f"Range:           {max_force - min_force:.6f} N")

print("\n" + "-"*60)
print(f"INITIAL OFFSET (First {initial_samples} samples):")
print("-"*60)
print(f"Mean:            {initial_mean:.6f} N")
print(f"Std deviation:   {initial_std:.6f} N")

print("\n" + "-"*60)
print("RECOMMENDED OFFSET VALUE:")
print("-"*60)
print(f"Use median:      {median_offset:.6f} N  (less sensitive to outliers)")
print(f"Or use initial:  {initial_mean:.6f} N  (baseline before load)")
print(f"Or use mean:     {mean_offset:.6f} N  (overall average)")

print("\n" + "="*60)
print("To correct for offset, subtract this value from all force measurements")
print("="*60)

