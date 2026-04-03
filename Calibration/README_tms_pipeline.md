# TMS 데이터 파이프라인 요약

이 문서는 현재 TMS 분석 파이프라인을 빠르게 이해하고 확인하기 위한 간단한 안내서입니다.

관련 스크립트:

- [tms_data_pipeline.py](/c:/Users/tae06/CODE/TMS/Calibration/tms_data_pipeline.py)
- [tms_exponential_temp.py](/c:/Users/tae06/CODE/TMS/Calibration/tms_exponential_temp.py)

## 1. 어떤 스크립트를 쓰면 되나

### `tms_data_pipeline.py`
기본 분석용 메인 파이프라인입니다.

- 로드셀 추력 분석
- 바로미터 압력 분석
- 드리프트 보정: `off`, `horizontal`
- 리포트, 처리 데이터, 플롯 저장

일반적인 정적연소 분석은 이 스크립트를 쓰면 됩니다.

### `tms_exponential_temp.py`
실험용 스크립트입니다.

- 지수형 드리프트 보정 테스트용
- 별도 drift reference 파일 필요
- 메인 워크플로우 대체용이 아니라 비교/실험용

## 2. 입력 데이터 가정

메인 파이프라인은 원본 TMS 텍스트 파일이 교차 저장(interleaved)되어 있다고 가정합니다.

- 채널 `0`: loadcell
- 채널 `1`: barometer

현재 설정:

```python
INPUT_FILENAME = "26.04.03 data.TXT"
LOADCELL_CHANNEL_INDEX = 0
BAROMETER_CHANNEL_INDEX = 1
SKIP_INITIAL_LINES = 2
SAMPLING_RATE = 320
```

해석 방식:

- 비어 있지 않은 앞 2줄은 건너뜀
- 이후 한 줄씩 번갈아 각 센서 데이터로 해석
- 샘플링은 `320 Hz` 고정 가정

시간축:

```python
time = np.arange(sample_count) / SAMPLING_RATE
```

## 3. 메인 파이프라인 순서

1. 교차 저장된 파일에서 loadcell/barometer 채널 분리
2. loadcell ADC를 force로 변환
3. barometer raw 값을 pressure로 변환
4. loadcell force에 drift correction 적용
5. force와 pressure에 low-pass filter 적용
6. pressure baseline 제거 후 gauge pressure 생성
7. 이벤트 검출 및 주요 지표 계산
8. 리포트, 데이터, 플롯 저장

이상할 때도 이 순서대로 확인하면 됩니다.

## 4. 변환식

### Loadcell

```python
force_N = (CALIBRATION_INTERCEPT + CALIBRATION_SLOPE * adc) * GRAVITATIONAL_CONSTANT + FORCE_OFFSET
```

현재 값:

```python
CALIBRATION_SLOPE = -0.0391
CALIBRATION_INTERCEPT = -193.0049
GRAVITATIONAL_CONSTANT = 9.80665
FORCE_OFFSET = 0.0
```

### Barometer

```python
pressure = PRESSURE_SLOPE * raw + PRESSURE_INTERCEPT
```

현재 값:

```python
PRESSURE_SLOPE = 0.0027
PRESSURE_INTERCEPT = -0.11
```

이 값은 이후 baseline 제거를 거쳐 gauge pressure로 사용됩니다.

## 5. 드리프트 보정

### `DRIFT_MODE = "off"`

보정 없이 원본 force를 그대로 사용합니다.

```python
modeled_drift = 0
corrected_force = raw_force
```

### `DRIFT_MODE = "horizontal"`

기본 보정 모드입니다.

동작 순서:

1. raw force를 low-pass filter
2. threshold 기반으로 ignition 시작점 추정
3. 그 시점의 절반 구간까지 평균 force 계산
4. 그 평균값을 전체 구간에서 빼서 baseline 보정

```python
corrected_force = raw_force - offset_force
offset_force = mean(raw_force[0 : ignition_idx // 2])
```

리포트에는 다음 값이 기록됩니다.

- offset 평균값
- 평균 구간 종료 시각
- 평균 샘플 수
- 검출된 ignition 시작 시각

## 6. 이벤트 검출

추력과 압력 모두 같은 방식으로 이벤트를 찾습니다.

```python
threshold_value = threshold_ratio * peak_value
```

- threshold를 처음 넘는 지점: 시작
- 마지막으로 넘는 지점: 종료

현재 설정:

```python
THRUST_EVENT_THRESHOLD_RATIO = 0.03
```

즉, peak의 `3%`를 기준으로 사용합니다.

## 7. 필터링

force와 pressure 모두 zero-phase Butterworth low-pass filter(`filtfilt`)를 사용합니다.

- 위상 지연 최소화
- 단순 1회 필터보다 타이밍 왜곡 감소

현재 설정:

```python
LOADCELL_LOWPASS_CUTOFF_HZ = 20.0
LOADCELL_LOWPASS_ORDER = 2
BAROMETER_LOWPASS_CUTOFF_HZ = 5.0
BAROMETER_LOWPASS_ORDER = 4
```

## 8. Pressure baseline

압력 baseline은 필터된 pressure 초반 구간 평균으로 계산합니다.

```python
pressure_baseline = mean(filtered_pressure[:baseline_count])
baseline_count = PRESSURE_BASELINE_WINDOW_SECONDS * SAMPLING_RATE
```

현재 값:

```python
PRESSURE_BASELINE_WINDOW_SECONDS = 0.5
```

이후:

```python
raw_gauge_pressure = raw_pressure - pressure_baseline
filtered_gauge_pressure = filtered_pressure - pressure_baseline
```

## 9. 주요 출력 지표

### Thrust

- peak thrust
- peak thrust time
- ignition time
- burnout time
- burn time
- pressure rise 대비 ignition delay
- total impulse
- average thrust
- specific impulse (`PROPELLANT_MASS`가 있을 때)

### Pressure

- peak pressure
- peak pressure time
- pressure rise time
- pressure span
- pressure mean
- pressure standard deviation

## 10. 출력 파일

출력 위치:

```text
Data/<YEAR>/<DATE_FOLDER>/analysis
```

현재 데이터셋 기준:

```text
Data/2026/4_2/analysis
```

생성 파일:

- `*_executive_report.txt`
- `*_pipeline_data.txt`
- `*_loadcell_summary.png`
- `*_barometer_summary.png`
- `*_combined_summary.png`

### `*_executive_report.txt`

사람이 읽기 좋은 요약 리포트입니다.

- thrust 지표
- drift correction 정보
- pressure 지표
- calibration 정보

### `*_pipeline_data.txt`

처리된 수치 데이터를 저장합니다.

- `time_s`
- `raw_force_N`
- `drift_model_N`
- `corrected_force_N`
- `filtered_force_N`
- `raw_gauge_pressure`
- `filtered_gauge_pressure`

수식이 제대로 적용됐는지 확인할 때 가장 중요한 파일입니다.

## 11. 플롯 의미

### Loadcell plot

- corrected force
- filtered thrust
- threshold line
- ignition / burnout marker
- burn region
- peak thrust marker

### Barometer plot

- raw gauge pressure
- filtered gauge pressure
- zero baseline
- peak pressure marker

### Combined plot

- 왼쪽 축: thrust
- 오른쪽 축: pressure
- 두 축의 zero 위치를 시각적으로 맞춰 비교

단위가 같다는 뜻은 아니고, 비교가 쉬우도록 정렬한 것입니다.

## 12. 신뢰성 확인 체크포인트

### 입력 확인

- 파일이 정말 interleaved 구조인지
- 채널 순서가 맞는지
- `SKIP_INITIAL_LINES`가 맞는지
- `SAMPLING_RATE`가 맞는지

### Horizontal offset 확인

- offset이 baseline 보정 수준인지
- 평균 구간 종료 시점이 ignition보다 충분히 앞인지
- 보정 후 점화 전 baseline이 0 근처인지

### Pressure baseline 확인

- baseline 제거 후 점화 전 pressure가 0 근처인지
- 첫 `0.5 s`가 조용한 구간인지

### Threshold 확인

- 약한 신호나 노이즈가 많은 경우 너무 일찍 잡히지 않는지
- thrust plot에서 threshold crossing이 자연스러운지

### Saved data 확인

가장 확실한 검증 순서:

1. `raw_force_N`
2. `drift_model_N`
3. `corrected_force_N = raw_force_N - drift_model_N`
4. `filtered_force_N`
5. `raw_gauge_pressure`
6. `filtered_gauge_pressure`

## 13. 언제 어떤 스크립트를 쓰나

[tms_data_pipeline.py](/c:/Users/tae06/CODE/TMS/Calibration/tms_data_pipeline.py):

- 일반 실험 분석
- 리포트 + 플롯 + 처리 데이터 필요
- `off` / `horizontal` drift 사용

[tms_exponential_temp.py](/c:/Users/tae06/CODE/TMS/Calibration/tms_exponential_temp.py):

- 지수형 drift 보정 시험
- drift reference 파일 보유
- 메인 파이프라인과 비교 실험

## 14. 빠른 실행 체크리스트

1. `INPUT_FILENAME`, 채널 인덱스, skip line, sampling rate 확인
2. 메인 파이프라인 실행
3. executive report 확인
4. horizontal offset 구간이 ignition 전에 끝나는지 확인
5. 점화 전 force baseline이 0 근처인지 확인
6. 점화 전 pressure baseline이 0 근처인지 확인
7. thrust threshold crossing 확인
8. 이상하면 `*_pipeline_data.txt` 확인
9. 기본 drift가 부족할 때만 exponential 스크립트 사용

## 15. 한 줄 정리

현재 메인 파이프라인은 정적연소 데이터를 빠르게, 반복 가능하게 정리하는 실용 분석 도구입니다.
가장 안전한 검증 방법은 `executive_report`와 `pipeline_data`를 함께 확인하는 것입니다.
