#ifndef HARMONICS_H
#define HARMONICS_H

#include <Arduino.h>

// for frequency estimate
extern float alpha; //smoothing factor
extern float avgFrequency;

// Variables for pitch estimation
extern volatile uint32_t lastZeroCrossTime;
extern volatile float fundamentalFreq;

// Variables for synthesized harmonic generation
extern float phaseIncBase;      // base freq increment at 20kHz PWM

// Nth Harmonic
extern float phaseNth;
extern float phaseIncNth;
extern float harmN;
extern float harmGainNth;
extern float harmPhaseNth;

// third harmonic
extern float phase3rd;
extern float phaseInc3rd;
extern float harmGain3rd;
extern float harmPhase3rd;

// fifth harmonic
extern float phase5th;
extern float phaseInc5th;
extern float harmGain5th;
extern float harmPhase5th;

// seventh harmonic
extern float phase7th;
extern float phaseInc7th;
extern float harmGain7th;
extern float harmPhase7th;

extern float dutyHarmonic;

#endif