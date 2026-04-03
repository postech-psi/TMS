#include <Adafruit_ADS1X15.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>

unsigned long lastMicros = 0;
unsigned long now = 0;
const unsigned long SAMPLING_INTERVAL = 3125; //  320sps 샘플링 간격 
unsigned long sampling_start_time = 0;
unsigned long current_interval = 0;

#define Loadcell 0x48 // datasheet 확인해야 함
#define Pressure 0x49 // datasheet 확인해야 함
#define CS_PIN 4 
#define interrupt_pin 2 // fire signal 받는 pin
#define relay 10  // relay control pin
#define relay_sig 9 // relay 상태 확인하는 pin

bool relaytrigger=false;
volatile bool ControlSignal=false;    

char filename[20];

Adafruit_ADS1115 ads1;
Adafruit_ADS1115 ads2;

volatile int16_t ads1_value = 0;
volatile int32_t ads2_value = 0;
File myfile;

void setup() {
  Serial.begin(115200); // baud rate 115200
  Wire.begin();     // I2C 시작
  SPI.begin();      // SPI 시작

  pinMode(relay,OUTPUT);
  digitalWrite(relay,LOW); // 처음에 이그나이터 릴레이는 열려있어야 함

  if (!ads1.begin(Loadcell)) {
    Serial.println("Loadcell ADS1 초기화 실패");
    //while (1);
  }
  if (!ads2.begin(Pressure)) {
    Serial.println("Pressure ADS2 초기화 실패");
    //while (1);
  }

  if (!SD.begin(CS_PIN)) {
    Serial.println("SD 카드 초기화 실패");
    //while (1);
  }
  
  int fileNumber = 1;
  sprintf(filename, "tms_%d.txt", fileNumber);
  while(SD.exists(filename)){
      fileNumber++;
      sprintf(filename, "tms_%d.txt", fileNumber);
  }


  ads1.setDataRate(RATE_ADS1115_860SPS);  // ADC 최대 샘플링 속도 설정
  ads1.setGain(GAIN_SIXTEEN);
  ads1.startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_0_1, /*continuous=*/true);

  ads2.setDataRate(RATE_ADS1115_860SPS);  // ADC 최대 샘플링 속도 설정
  ads2.setGain(GAIN_ONE);
  ads2.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, /*continuous=*/true);

  // rising edge interrupt: 점화 신호가 들어오면 start_func 실행
  attachInterrupt(digitalPinToInterrupt(interrupt_pin), start_func, RISING);

  // sd 카드 처음 write 시 발생하는 문제 방지 위해서 한번 열었다가 닫아줌: github issue 참고
  myfile=SD.open(filename,FILE_WRITE);
  ads1_value =  ads1.getLastConversionResults();
  // Serial.println(ads1_value);
  ads2_value =  ads2.getLastConversionResults();
  // Serial.println(ads2_value);
  myfile.println(ads1_value);
  myfile.println(ads2_value);
  Serial.println(filename);
  myfile.close();
  // Serial.println("Setup FInished");
}

void loop() { 
  if(ControlSignal){  // 점화 신호 받는게 확인되면 loop 진입
    int fileNumber = 1;
    sprintf(filename, "tms_%d.txt", fileNumber);
    while(SD.exists(filename)){
      fileNumber++;
      sprintf(filename, "tms_%d.txt", fileNumber);
    }
    Serial.println(filename);
    myfile=SD.open(filename,FILE_WRITE);

    digitalWrite(relay,HIGH); // igniter relay 닫기

    // relay가 제대로 닫혔는지 확인 후 샘플링 시작
    while(!relaytrigger){  
      if(digitalRead(relay_sig)==HIGH){
        relaytrigger=true;
      }
    }

    sampling_start_time = micros();
    now = sampling_start_time + 1;


    while(now-sampling_start_time<15000000){  // 15 초 동안 샘플링
      lastMicros = micros();

      ads1_value =  ads1.getLastConversionResults();
      // Serial.println(ads1_value);
      ads2_value =  ads2.getLastConversionResults();
      // Serial.println(ads2_value);

      myfile.println(ads1_value);
      myfile.println(ads2_value);

      // 점화 신호 low 되면 relay 열기
      if(digitalRead(2)==LOW){  
        digitalWrite(relay, LOW); 
        }
  
      now = micros();

      // 샘플링 간격 맞추기: 샘플링 간격보다 빠르게 루프가 돌면 delay로 간격 맞춰주기
      current_interval = now - lastMicros;
      if (current_interval <= SAMPLING_INTERVAL) {
          delayMicroseconds(SAMPLING_INTERVAL - current_interval);
        } 

    }

    //Serial.println("end sampling");
    ControlSignal=false;
    myfile.close();
    digitalWrite(relay,LOW);
    // Serial.print("ignitor opened");
    relaytrigger=false;
  }
}

// fire signal 받으면 50번 샘플링해서 45번 이상 HIGH면 ControlSignal true로 바꿔주는 함수
void start_func(){
  int count=0;
  for(int i=0;i<50;i++){
    delay(10);
    if(digitalRead(2)==HIGH){
      count++;
    }
  }
  if(count>45){
    ControlSignal=true; 
  }
}
