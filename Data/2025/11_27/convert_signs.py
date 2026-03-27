"""
Script to convert all number signs in calibration data files
Converts TEST_*.TXT files by negating all numeric values
"""
import os

# ===== CONFIGURATION =====
data_dir = '/Users/leetaeho/TMS/Data/11_27/calidata'
output_dir = '/Users/leetaeho/TMS/Data/11_27/calidata_positive'
# =========================

# Create output directory if it doesn't exist
os.makedirs(output_dir, exist_ok=True)

# Read and convert all numbers
converted_count = 0
for i in range(20):
    filename = f'TEST_{i}.TXT'
    input_filepath = os.path.join(data_dir, filename)
    output_filepath = os.path.join(output_dir, filename)
    
    # Skip if input file doesn't exist
    if not os.path.isfile(input_filepath):
        print(f"파일 없음: {filename}")
        continue

    converted_lines = []
    with open(input_filepath, 'r') as file:
        for line in file:
            line = line.strip()
            if line:  # If line is not empty
                try:
                    number = float(line)
                    # Convert sign (multiply by -1)
                    converted_number = -number
                    converted_lines.append(f"{converted_number}\n")
                except ValueError:
                    # If not a number, keep as is
                    converted_lines.append(f"{line}\n")
            else:
                converted_lines.append("\n")

    # Write to output file
    with open(output_filepath, 'w') as file:
        file.writelines(converted_lines)
    
    converted_count += 1
    print(f"✓ 변환 완료: {filename}")

print(f"\n모든 파일 변환 완료!")
print(f"  변환된 파일 수: {converted_count}")
print(f"  출력 디렉토리: {output_dir}")

