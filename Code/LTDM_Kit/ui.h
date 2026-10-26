#ifndef UI_H
#define UI_H

#include <Arduino.h>
#include "Adafruit_TLC5947.h"

extern uint8_t currentInput;
extern bool UI_ReadPhase;
extern uint32_t lastPrint;
extern Adafruit_TLC5947 tlc;

// Button state array
extern volatile bool buttonStates[16];
extern volatile float sliderStates[16];
extern volatile float pedalStates[2];
extern volatile float myFreq;
extern volatile float inputSum;
extern volatile float myQ;
extern volatile int LeafOK;
void initUI();
void initServo();
void readUI();
void updateSevo();
void updateLEDsFromButtons();
void output();

#endif