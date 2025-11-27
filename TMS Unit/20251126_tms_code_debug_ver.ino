#include <Adafruit_ADS1X15.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>

unsigned long lastMicros = 0;
unsigned long now = 0;
const unsigned long interval = 3125; //  320sps
unsigned long sampling_start_time = 0;

#define Loadcell 0x48 // datasheet 확인해야 함
#define Pressure 0x49 // datasheet 확인해야 함
#define CS_PIN 4
#define interrupt_pin 2 // control signal 받는 선
#define relay 10
#define relay_sig 9

bool relaytrigger=false;
volatile bool ControlSignal=false;    

char filename[20];

Adafruit_ADS1115 ads1;
Adafruit_ADS1115 ads2;

volatile int16_t ads1_value = 0;
volatile int32_t ads2_value = 0;
File myfile;

//uint16_t 

void setup() {
  Serial.begin(115200); // baud rate 115200
  Serial.println("=== BOOT ===");
  Wire.begin();     // I2C 시작
  SPI.begin();      // SPI 시작

  pinMode(relay,OUTPUT);
  digitalWrite(relay,LOW); // 초기 이그나이터 릴레이는 열려있어야 함

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
    Serial.print("SD CARD");
      fileNumber++;
      sprintf(filename, "tms_%d.txt", fileNumber);
  }


  ads1.setDataRate(RATE_ADS1115_860SPS);  // 최대 속도 설정
  ads1.setGain(GAIN_SIXTEEN);
  ads1.startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_0_1, /*continuous=*/true);

  ads2.setDataRate(RATE_ADS1115_860SPS);  // 최대 속도 설정
  ads2.setGain(GAIN_ONE);
  ads2.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, /*continuous=*/true);
  attachInterrupt(digitalPinToInterrupt(interrupt_pin), start_func, RISING);

  myfile=SD.open(filename,FILE_WRITE);
  ads1_value =  ads1.getLastConversionResults();
  Serial.println(ads1_value);
  ads2_value =  ads2.getLastConversionResults();
  Serial.println(ads2_value);
  myfile.println(ads1_value);
  myfile.println(ads2_value);
  Serial.println(filename);
  myfile.close();
  Serial.println("Setup FInished");
}

void loop() {
  if(ControlSignal){
    int fileNumber = 1;
    sprintf(filename, "tms_%d.txt", fileNumber);
    while(SD.exists(filename)){
      Serial.print("SD CARD");
      fileNumber++;
      sprintf(filename, "tms_%d.txt", fileNumber);
    }
    Serial.println(filename);
    myfile=SD.open(filename,FILE_WRITE);

    Serial.println("start sampling");
    digitalWrite(relay,HIGH); // igniter relay 신호 전달

    while(!relaytrigger){
      Serial.println("relaytrigger");
      if(digitalRead(relay_sig)==HIGH){
        relaytrigger=true;
      }
    }
    sampling_start_time=micros();
    now = sampling_start_time + 1;
    Serial.println("before while");
    while(now-sampling_start_time<15000000){ // 15 seconds
      lastMicros = micros();
      Serial.println("after while");
      ads1_value =  ads1.getLastConversionResults();
      Serial.println(ads1_value);
      ads2_value =  ads2.getLastConversionResults();
      Serial.println(ads2_value);
      myfile.println(ads1_value);
      myfile.println(ads2_value);
      Serial.println("After write");
      if(digitalRead(2)==LOW){  // if power is disconnected
        digitalWrite(relay, LOW); // igniter opened
        Serial.println("Relay Open");
        }
      Serial.println("After relay opened");
      now = micros();
      if (now - lastMicros <= interval) {
          delayMicroseconds(interval - (now - lastMicros));
        }
      else
      {
        myfile.println("over");
      }
      Serial.println("Cycle");

    }
    //Serial.println("end sampling");
    ControlSignal=false;
    myfile.close();
    digitalWrite(relay,LOW);
    // Serial.print("ignitor opened");
    relaytrigger=false;
  }
}


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