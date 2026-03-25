#include "ui.h"
#include "pinmap.h"
#include "flexpwm.h"
#include <Arduino.h>
#include <SPI.h>
#include "Adafruit_TLC5947.h"
#include <cstdint>
#include "render.h"

extern float currRMS;

volatile bool buttonStates[16] = {};
volatile float sliderStates[16] = {};
volatile float pedalStates[2] = {};

uint8_t currentInput = 0;
bool UI_ReadPhase = false;
uint32_t lastPrint = 0;

extern Adafruit_TLC5947 tlc = Adafruit_TLC5947(1, tlc_clock, tlc_data, tlc_latch);

void initUI() {
  pinMode(DSIN, INPUT_PULLUP);
  pinMode(DS0, OUTPUT);
  pinMode(DS1, OUTPUT);
  pinMode(DS2, OUTPUT);
  pinMode(DS3, OUTPUT);

  pinMode(ASIN, INPUT);
  pinMode(AS0, OUTPUT);
  pinMode(AS1, OUTPUT);
  pinMode(AS2, OUTPUT);
  pinMode(AS3, OUTPUT);

  pinMode(FP0, INPUT);
  pinMode(FP1, INPUT);

  digitalWrite(DS0, LOW);
  digitalWrite(DS1, LOW);
  digitalWrite(DS2, LOW);
  digitalWrite(DS3, LOW);
  
  digitalWrite(AS0, LOW);
  digitalWrite(AS1, LOW);
  digitalWrite(AS2, LOW);
  digitalWrite(AS3, LOW);

  tlc.begin();
}

// Remap table: reorders where each pot value is stored (since the default hardware inputs was wack)
const uint8_t sliderRemap[16] = {7, 6, 5, 4, 0, 1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15};

void readUI(){
  if (!UI_ReadPhase) {
    // MUX select pins based on currentButton index
    digitalWrite(DS0, currentInput & 0x01);
    digitalWrite(DS1, (currentInput >> 1) & 0x01);
    digitalWrite(DS2, (currentInput >> 2) & 0x01);
    digitalWrite(DS3, (currentInput >> 3) & 0x01);
    digitalWrite(AS0, currentInput & 0x01);
    digitalWrite(AS1, (currentInput >> 1) & 0x01);
    digitalWrite(AS2, (currentInput >> 2) & 0x01);
    digitalWrite(AS3, (currentInput >> 3) & 0x01);
    UI_ReadPhase = 1;
  } else {
    buttonStates[currentInput] = (digitalRead(DSIN) == LOW);
    sliderStates[sliderRemap[currentInput]] = float(analogRead(ASIN)/4096.);
    if (currentInput == 0) {pedalStates[0] = float(analogRead(FP0)/4096.);}
    else if (currentInput == 1) {pedalStates[1] = float(analogRead(FP1)/4096.);}
    // Move to next button
    currentInput = (currentInput + 1) & 0x0F;
    UI_ReadPhase = 0;
  }
}

void updateLEDsFromButtons() {
  //tlc.setLED(LED_INDEX, R, G, B);
  tlc.setLED(0, 0, 500*sliderStates[0]*buttonStates[0], 0); // CH1 - turn LED on when active
  tlc.setLED(1, 0, 500*sliderStates[4]*buttonStates[1], 0); // CH2 - turn LED on when active
  tlc.write();
  delay(1);
}

// this is naughty ... I have tied together serial printing and updating the buttons
void output() {
  // put your main code here, to run repeatedly:
  if (millis() - lastPrint > 100) {
    lastPrint = millis();
    for (int i = 0; i < 16; i++){
      Serial.print(buttonStates[i]);
    }
    for (int i = 0; i < 16; i++){
      Serial.print(" ");
      Serial.print(sliderStates[i]);
    }
    Serial.print(" ");
    Serial.print(pedalStates[0]);
    Serial.print(" ");
    Serial.print(pedalStates[1]);

    Serial.println();
    Serial.print("adcScale: ");
    Serial.print(context.ch[0].adcScale);
    Serial.print(" targetRMS: ");
    Serial.print(context.ch[0].targetRMS);
    Serial.print(" measuredRMS: ");
    Serial.print(context.ch[0].measuredRMS);
    Serial.print(" noiseScale: ");
    Serial.print(" ");
    Serial.print(context.ch[0].noiseScale);
    Serial.println();

    Serial.print("adcScale: ");
    Serial.print(context.ch[1].adcScale);
    Serial.print(" targetRMS: ");
    Serial.print(context.ch[1].targetRMS);
    Serial.print(" measuredRMS: ");
    Serial.print(context.ch[1].measuredRMS);
    Serial.print(" noiseScale: ");
    Serial.print(" ");
    Serial.print(context.ch[1].noiseScale);
    Serial.println();

    Serial.print(currRMS);
    Serial.println();

    updateLEDsFromButtons();
  }
}