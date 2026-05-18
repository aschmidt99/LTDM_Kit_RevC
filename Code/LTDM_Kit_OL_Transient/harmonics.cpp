#include "harmonics.h"
#include "system_config.h"
#include <Arduino.h>

// for frequency estimate
float alpha = 0.4f; //smoothing factor
float avgFrequency = 0;

// Variables for pitch estimation
volatile uint32_t lastZeroCrossTime = 0;
volatile float fundamentalFreq = 0;

// Variables for synthesized harmonic generation
float phaseIncBase = fundamentalFreq / float(SAMPLERATE);      // base freq increment at 20kHz PWM

// Nth Harmonic
float phaseNth = 0.0f;
float phaseIncNth = phaseIncBase;
float harmN = 2.0;
float harmGainNth = 0.0;
float harmPhaseNth = 0.0;

// third harmonic
float phase3rd = 0.0f;
float phaseInc3rd = phaseIncBase * 3.0f;              // 3rd harmonic increment
float harmGain3rd = 0.0;
float harmPhase3rd = 0.0;

// fifth harmonic
float phase5th = 0.0f;
float phaseInc5th = phaseIncBase * 5.0f;              // 5th harmonic increment
float harmGain5th = 0.0;
float harmPhase5th = 0.0;

// seventh harmonic
float phase7th = 0.0f;
float phaseInc7th = phaseIncBase * 1.0f;              // 7th harmonic increment
float harmGain7th = 0.0;
float harmPhase7th = 0.0;

float dutyHarmonic = 0.0f;

void updateAvgFrequency(float frequency) {
  if (avgFrequency == 0) {
    avgFrequency = frequency;
  } else {
  avgFrequency = alpha * frequency + (1 - alpha) * avgFrequency; //
  }
}

 // // THE FOLLOWING NEEDS TO MIGRATE TO RENDER.CPP /OR/ BE RE-MANAGED TO BE A PART OF EACH CHANNEL
    
  //   // GAIN SET BY FIRST KNOB COLUMN 
  //   // CH1.fbGain = sliderStates[0]*4.0;
  //   // CH2.fbGain = sliderStates[4]*4.0;

  //   // TARGET RMS SET BY 2ND KNOB COLUMN
  //   CH1.targetRMS = sliderStates[1]*4096;
  //   // CH1.targetRMS = pedalStates[0]*4096; // USE PEDAL INSTEAD
  //   CH2.targetRMS = sliderStates[5]*4096;

  //   // ADC SCALE WHEN MEASURED RMS TOO BIG
  //   CH1.adcScale = constrain(((float)CH1.targetRMS - (float)CH1.measuredRMS)/1024.0, 0.0, 3.0);
  //   CH2.adcScale = constrain(((float)CH2.targetRMS - (float)CH2.measuredRMS)/1024.0, 0.0, 3.0);

  //   // CH2.adcScale = constrain(1.0 - (CH2.measuredRMS-CH2.targetRMS)/1024.0, 0.0, 1.0);

  //   // MAX NOISE SENT BY 4TH KNOB COLUMN
  //   noise = random(-4096, 4096); // Same noise signal can be used for both
  //   CH1.noiseScale = sliderStates[3]*(constrain(1.0 - (CH1.measuredRMS/1024.0), 0.0, 1.0))*(float)CH1.targetRMS/4096.0f; // divide by 4096 instead of 2048 to leave more noise in the system. Noise currently cuts out entirely when RMS is half of ADC range
  //   CH2.noiseScale = sliderStates[7]*(constrain(1.0 - (CH2.measuredRMS/1024.0), 0.0, 1.0))*(float)CH2.targetRMS/4096.0f; // divide by 4096 instead of 2048 to leave more noise in the system. Noise currently cuts out entirely when RMS is half of ADC range

  //   CH1.activeDamp = buttonStates[8];
  //   CH2.activeDamp = buttonStates[9];

  //   ///CALCULATE RMS
  //   updateRMS(CH1);
  //   updateRMS(CH2);

    // harmonic synthesis omitted for time being
    //
    // // for zero crossing detection
    // if (CH1_polValue != CH1_lastPolValue && CH1_polValue) { //rising edge only
    //   uint32_t currentTime = micros();
    //   uint32_t period = currentTime - lastZeroCrossTime;
    //   lastZeroCrossTime = currentTime;
    //   if (period > 0){
    //     fundamentalFreq = 1e6 / float(period); // Frequency in Hz assuming micros()
    //   }
    //   DEBUG_PRINT(harmN);
    //   DEBUG_PRINT(' ');
    //   // DEBUG_PRINT(500);
    //   // DEBUG_PRINT(' ');
    //   // DEBUG_PRINT(0);
    //   // DEBUG_PRINT(' ');
    //   DEBUG_PRINT(fundamentalFreq);
    //   DEBUG_PRINT(' ');
    //   DEBUG_PRINTLN(avgFrequency);
    //   // if (fundamentalFreq < 500) {
    //     updateAvgFrequency(fundamentalFreq);
    //   // } // remove outliers
    // }
    // CH1_lastPolValue = CH1_polValue;
    //
    // // THINGS THAT CAN BE SLOW OR BEHIND BY 1 SAMPLE: ////
    // fbGain = (analogRead(POT_PIN3)/1204.0); //Read analog pin to determine feedback gain
    // harmGain3rd = (analogRead(POT_PIN2)/4.0); //Read analog pin to determine 3rd harmonic gain
    // harmGain5th = (analogRead(POT_PIN4)/4.0); // Read analog pin to determine 4th harmonic gain
    // // harmGain7th = (analogRead(POT_PIN1)/4.0); // Read analog pin to determine 4th harmonic gain

    // harmN = (analogRead(POT_PIN2)/455+2);
    // harmGainNth = (analogRead(POT_PIN4)/2.0);

    // harmPhase3rd = analogRead(POT_PIN1) / 4095.0; //Read analog pin to adjust harmonic phase
    // harmPhase3rd = 0; //Read analog pin to adjust harmonic phase
    // harmPhase5th = harmPhase3rd; // for now, same phase offset for both
    // harmPhase7th = harmPhase3rd; // for now, same phase offset for both
    // harmPhaseNth = harmPhase3rd; // for now, same phase offset for both


    // phaseIncBase = avgFrequency / float(SAMPLERATE);      // base freq increment at 20kHz PWM
    
    // // Arbitrary Nth harmonic handlings
    // phaseIncNth = phaseIncBase * float(harmN);              // Nth
    // phaseNth += phaseIncNth;
    // if (phaseNth >= 1.0f) phaseNth -= 1.0f;

    // //apply phase offset
    // float adjustedPhaseNth = phaseNth + harmPhaseNth;
    // if (adjustedPhaseNth >= 1.0f) adjustedPhaseNth -= 1.0f;


    // //////// 3RD HARMONIC
    // phaseInc3rd = phaseIncBase * 3.0f;              // 3rd harmonic increment
    // phase3rd += phaseInc3rd;
    // if (phase3rd >= 1.0f) phase3rd -= 1.0f;

    // float adjustedPhase3rd = phase3rd + harmPhase3rd;    //apply phase offset
    // if (adjustedPhase3rd >= 1.0f) adjustedPhase3rd -= 1.0f;

    // //////// 5TH HARMONIC
    // phaseInc5th = phaseIncBase * 5.0f;              // 5th harmonic increment
    // phase5th += phaseInc5th;
    // if (phase5th >= 1.0f) phase5th -= 1.0f;

    // float adjustedPhase5th = phase5th + harmPhase5th;
    // if (adjustedPhase5th >= 1.0f) adjustedPhase5th -= 1.0f;

    // //////// 7TH HARMONIC
    // phaseInc7th = phaseIncBase * 1.0f;              // 7th harmonic increment
    // phase7th += phaseInc7th;
    // if (phase7th >= 1.0f) phase7th -= 1.0f;

    // float adjustedPhase7th = phase7th + harmPhase7th;    // apply phase offset
    // if (adjustedPhase7th >= 1.0f) adjustedPhase7th -= 1.0f;

    // // create 3rd harmonic waveform (square)
    // // float harmonicVal = (adjustedPhase < 0.5f) ? 1.0f : -1.0f;
    // // create 3rd harmonic waveform (sine)
    // float harmonicValNth = getSineFromTable(adjustedPhaseNth);
    // // float harmonicVal3rd = getSineFromTable(adjustedPhase3rd);
    // // float harmonicVal5th = getSineFromTable(adjustedPhase5th);
    // // float harmonicVal7th = getSineFromTable(adjustedPhase7th);
    // // dutyHarmonic = harmonicVal3rd * harmGain3rd + harmonicVal5th * harmGain5th + harmonicVal7th * harmGain7th + harmonicValNth * harmGainNth;
    // dutyHarmonic = harmonicValNth * harmGainNth;