#include <Adafruit_ADS1X15.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>

unsigned long lastMicros = 0;
const unsigned long interval = 2000; // 500sps

#define Loadcell 0x48 // datasheet 확인해야 함
#define Pressure 0x49 // datasheet 확인해야 함
#define CS_PIN 4
#define interrupt_pin 2 // control signal 받는 선
#define relay 10
#define relay_sig 9

Adafruit_ADS1115 ads1;

volatile int16_t ads1_value = 0;
int num = 0;
File myfile;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  SPI.begin();

  pinMode(relay, OUTPUT);
  digitalWrite(relay, LOW);

  if (!ads1.begin(Loadcell)) {
    Serial.println("Loadcell ADS1 초기화 실패");
    while (1);
  }

  if (!SD.begin(CS_PIN)) {
    Serial.println("SD 카드 초기화 실패");
    while (1);
  }

  ads1.setDataRate(RATE_ADS1115_860SPS);
  ads1.setGain(GAIN_SIXTEEN);
  ads1.startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_0_1, true);

  // 존재하지 않는 test_i.txt 파일을 찾아 생성
  int count = -1;
  char filename[20];
  for (int i = 0; i <= 20; i++) {
    snprintf(filename, sizeof(filename), "test_%d.txt", i);
    if (!SD.exists(filename)) {
      count = i;
      break;
    }
  }

  if (count == -1) {
    Serial.println("모든 test_0~20.txt 파일이 존재합니다. 종료합니다.");
    while (1);
  }

  // 파일 열기
  myfile = SD.open(filename, FILE_WRITE);
  if (!myfile) {
    Serial.println("파일 열기 실패");
    while (1);
  }

  Serial.print("파일 열림: ");
  Serial.println(filename);

  num = 0;
}

void loop() {
  if (num == 0) {
    digitalWrite(relay, HIGH);
    long long int timer = 0;
    float sum = 0;
    while (true) {
      unsigned long now = micros();
      if (now - lastMicros >= interval) {
        lastMicros = now;
        ads1_value = ads1.getLastConversionResults();
        sum += float(ads1_value);

        myfile.println(ads1_value);
        Serial.println(ads1_value);
        timer++;
      }
      if (timer > 3000) {
        myfile.close();
        break;
      }
    }
    num = 1; // loop 종료를 위해
    digitalWrite(relay, LOW);
  }
}