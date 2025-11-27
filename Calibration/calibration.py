import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
import os

data_dir = 'E:/'
measured_value = []

for i in range(20):
    filename = f'test_{i}.txt'
    filepath = os.path.join(data_dir, filename)

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
            measured_value.append(None)
value= np.array(measured_value)
print(value)
value= np.array(measured_value).reshape(-1, 1)
truevalue = np.array([0, 6.5, 9.43, 12.47, 15.39, 18.42, 21.46, 24.42, 27.4, 30.41, 32.22, 34.03, 35.84, 37.65, 39.46, 41.26, 43.03, 44.86, 46.72, 48.52])
print(truevalue)
# Linear Regression Model
model = LinearRegression()
model.fit(value, truevalue)

# Predict for plotting
predicted = model.predict(value)

# Coefficients
slope = model.coef_[0]
intercept = model.intercept_
print(f"Best fit line: y = {slope:.4f}x + {intercept:.4f}")

# Plot
plt.figure(figsize=(8, 5))
plt.scatter(value, truevalue, label='Data')
plt.plot(value, predicted, color='red', label=f'Best fit: y = {slope:.4f}x + {intercept:.2f}')
plt.xlabel("measured_value")
plt.ylabel("true_value(kg)")
plt.title("Load_Cell Calibration")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()


