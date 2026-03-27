# Thrust Measurement System (TMS)

TMS는 정적 연소 시험(static fire test)에서 추력을 계측하기 위한 Arduino Nano 기반 데이터 수집 시스템입니다.  
펌웨어는 점화 신호와 센서 기록을 제어하고, Python 스크립트는 저장된 로그를 보정·분석합니다.

## Repo 구성

- `TMS Unit/`
  - Arduino 펌웨어 (`20251126_tms_code.ino`, `20251126_tms_code_debug_ver.ino`)
- `Calibration/`
  - 로드셀 보정, raw 데이터 변환, 추력 곡선 분석 스크립트
- `Data/`
  - 측정 로그와 분석 결과 예시

## 펌웨어 작동 타임라인 

1. 부팅 시 `setup()`이 한 번 실행됩니다.
2. ADC, SD 카드, 인터럽트를 초기화합니다.
3. 이후 `loop()`는 계속 반복되며 시작 신호를 기다립니다.
4. pin 2에 시작 신호가 들어오면 인터럽트가 `start_func()`를 실행합니다.
5. `start_func()`가 신호를 확인한 뒤 `ControlSignal = true`로 바꿉니다.
6. `loop()`가 이를 감지하면 릴레이를 켭니다.
7. 릴레이가 제대로 닫혔는지 확인하기 위해 `relay_sig`가 HIGH가 될 때까지 기다립니다.
8. 확인이 끝나면 약 15초 동안 센서 값을 읽어 SD 카드에 저장합니다.
9. 종료 후 파일을 닫고 릴레이를 끈 뒤 다시 대기 상태로 돌아갑니다.

## 신호와 핀 역할

| 이름 | 핀 | 역할 |
| --- | --- | --- |
| `interrupt_pin` | 2 | 시작 신호 입력 |
| `relay` | 10 | 릴레이 제어 출력 |
| `relay_sig` | 9 | 릴레이 동작 확인 입력 |
| `CS_PIN` | 4 | SD 카드 chip select |
| `Loadcell` | `0x48` | 로드셀용 ADS1115 주소 |
| `Pressure` | `0x49` | 압력센서용 ADS1115 주소 |
