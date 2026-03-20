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