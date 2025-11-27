#!/usr/bin/env python3
"""
TMS File Sampling Rate (Hz) Checker
Analyzes a 15-second TMS data file and calculates actual sampling frequency
"""

import os
import sys

def check_hertz(filename, duration_seconds=15):
    """
    Check sampling rate of TMS data file
    
    Args:
        filename: Path to the data file
        duration_seconds: Expected duration in seconds (default: 15)
    
    Returns:
        dict: Analysis results
    """
    
    if not os.path.exists(filename):
        print(f"ERROR: File not found: {filename}")
        return None
    
    # Read file and count lines
    line_count = 0
    numeric_count = 0
    
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if line:  # Skip empty lines
                line_count += 1
                # Check if line is numeric
                try:
                    float(line)
                    numeric_count += 1
                except ValueError:
                    pass  # Not numeric (like "over")
    
    # Calculate sampling rate
    # Each sample = 2 lines (ads1_value, ads2_value)
    total_samples = line_count / 2.0
    sampling_rate = total_samples / duration_seconds
    
    # Expected values
    expected_interval = 3125  # microseconds
    expected_rate = 1000000.0 / expected_interval  # 320 Hz
    expected_samples = expected_rate * duration_seconds
    
    # Calculate error
    difference = sampling_rate - expected_rate
    percent_error = (difference / expected_rate) * 100.0
    actual_interval = 1000000.0 / sampling_rate if sampling_rate > 0 else 0
    
    results = {
        'filename': filename,
        'duration': duration_seconds,
        'line_count': line_count,
        'numeric_count': numeric_count,
        'total_samples': total_samples,
        'sampling_rate': sampling_rate,
        'expected_rate': expected_rate,
        'expected_samples': expected_samples,
        'difference': difference,
        'percent_error': percent_error,
        'actual_interval': actual_interval,
        'expected_interval': expected_interval
    }
    
    return results

def print_results(results):
    """Print formatted results"""
    if results is None:
        return
    
    print("\n" + "="*50)
    print("TMS FILE SAMPLING RATE ANALYSIS")
    print("="*50)
    print(f"\nFile: {results['filename']}")
    print(f"Duration: {results['duration']} seconds")
    print()
    
    print("FILE STATISTICS:")
    print(f"  Total lines: {results['line_count']}")
    print(f"  Numeric values: {results['numeric_count']}")
    print(f"  Estimated samples: {results['total_samples']:.1f}")
    print()
    
    print("SAMPLING RATE:")
    print(f"  Actual rate: {results['sampling_rate']:.2f} Hz")
    print(f"  Expected rate: {results['expected_rate']:.2f} Hz")
    print(f"  Expected samples: {int(results['expected_samples'])}")
    print()
    
    print("ANALYSIS:")
    print(f"  Difference: {results['difference']:.2f} Hz")
    print(f"  Error: {results['percent_error']:.2f} %")
    print()
    
    print("TIMING:")
    print(f"  Actual interval: {results['actual_interval']:.2f} microseconds")
    print(f"  Expected interval: {results['expected_interval']} microseconds")
    print()
    
    # Status
    if abs(results['percent_error']) < 1.0:
        print("✓ Status: Sampling rate is ACCURATE!")
    elif abs(results['percent_error']) < 5.0:
        print("⚠ Status: Sampling rate is CLOSE to expected")
    else:
        print("✗ Status: Sampling rate DIFFERS significantly")
    
    print("="*50 + "\n")

if __name__ == "__main__":
    # Default file
    default_file = "TMS_2.TXT"
    
    # Get filename from command line or use default
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = default_file
        print(f"Using default file: {filename}")
        print("Usage: python check_hertz.py [filename] [duration_seconds]")
        print()
    
    # Get duration from command line or use default
    duration = 15
    if len(sys.argv) > 2:
        try:
            duration = float(sys.argv[2])
        except ValueError:
            print(f"Invalid duration: {sys.argv[2]}, using default: 15 seconds")
    
    # Analyze
    results = check_hertz(filename, duration)
    
    if results:
        print_results(results)
    else:
        sys.exit(1)


