# truevalue = np.array 에 벽돌 올려놓는 순서대로 질량을 적어주어야 함
# 해당 날짜의 폴더에 있는 cali_weights.txt 파일을 읽어서 truevalue로 사용할 수 있도록 함

import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
import os
from pathlib import Path

# 년도와 날짜를 이름으로 폴더 만들고 그 안에 calidata 폴더와 cali_weights.txt 파일 넣어주기 
YEAR = "2026"
DATE_FOLDER = "4_2"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
data_dir = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER / "calidata"
weights_file = PROJECT_ROOT / "Data" / YEAR / DATE_FOLDER / "cali_weights.txt"
measured_value = []

data_files = sorted(
    filename
    for filename in os.listdir(data_dir)
    if filename.upper().startswith("TEST") and filename.upper().endswith(".TXT")
)

for filename in data_files:
    filepath = data_dir / filename

    if not os.path.isfile(filepath):
        print(f"파일 없음: {filename}")
        continue

    with open(filepath, 'r') as file:
        lines = file.readlines()
        try:
            numbers = [float(line.strip()) for line in lines if line.strip() != '']
            if len(numbers) == 0:
                print(f"빈 파일: {filename}")
                continue
            average = sum(numbers) / len(numbers)
            measured_value.append(average)
        except ValueError:
            print(f"숫자 변환 오류: {filename}")
            continue

value = np.array(measured_value).reshape(-1, 1)
print(f"로드셀 평균 값: {value.flatten()}")

if os.path.isfile(weights_file):
    print(f"증분 질량 파일: {weights_file}")
    weigths = np.loadtxt(weights_file)
else:
    print(f"증분 질량 파일 없음, 직접 입력값 사용")
    weigths = np.array([0, 6.785, 2.92, 3.07, 5.98, 5.85, 6.10, 5.98, 3.65, 3.62, 3.60])

truevalue = np.cumsum(weigths)
print(f"누적 질량 값 (kg): {truevalue}")

# Validate array lengths match
if len(value) != len(truevalue):
    raise ValueError(f"값 불일치: {len(value)} 측정값 but {len(truevalue)} 증분 질량 값!")

# Linear Regression Model
model = LinearRegression()
model.fit(value, truevalue)

# Predict for plotting
predicted = model.predict(value)

# Coefficients
slope = model.coef_[0]
intercept = model.intercept_
r_squared = model.score(value, truevalue)
print(f"Best fit line: y = {slope:.4f}x + {intercept:.4f}")
print(f"R²: {r_squared:.6f}")

# Plot
plt.figure(figsize=(8, 5))
plt.scatter(value, truevalue, label='Data')
plt.plot(value, predicted, color='red', label=f'Best fit: y = {slope:.4f}x + {intercept:.2f}')
plt.xlabel("measured_value")
plt.ylabel("true_value(kg)")
plt.title(f"Load_Cell Calibration (R² = {r_squared:.4f})")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()
