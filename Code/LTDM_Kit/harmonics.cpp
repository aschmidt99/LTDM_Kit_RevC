// harmonics.cpp
#include "harmonics.h"
#include "system_config.h"
#include "SineTable.h"
#include <Arduino.h>

float alpha = 0.99f; //smoothing factor for fundamental frequency estimate

float avgFrequency[NUM_CHANNELS] = {0.0f, 0.0f};

// Variables for pitch estimation
volatile uint32_t lastZeroCrossTime[NUM_CHANNELS] = {0, 0};
volatile float fundamentalFreq[NUM_CHANNELS] = {0.0f, 0.0f};

float harmPhase[NUM_CHANNELS][NUM_HARMONICS] = {};
float harmGain[NUM_HARMONICS] = {};

static bool lastPolarity[NUM_CHANNELS] = {false, false};

void updateAvgFrequency(int chan, float frequency) {
  if (avgFrequency[chan] == 0) {
    avgFrequency[chan] = frequency;
  } else {
    avgFrequency[chan] = alpha * frequency + (1 - alpha) * avgFrequency[chan]; //
  }
}

void updateHarmonicPitch(int chan, bool polarityHigh) {
  if (polarityHigh && !lastPolarity[chan]) {
    uint32_t now = micros();
    uint32_t period = now - lastZeroCrossTime[chan];
    lastZeroCrossTime[chan] = now;
    if (period > 0) {
      fundamentalFreq[chan] = 1e6f / float(period); //Hz, from micros() period
      updateAvgFrequency(chan, fundamentalFreq[chan]);
    }
  }
  lastPolarity[chan] = polarityHigh;
}

float renderHarmonics(int chan) {
  float sum = 0.0f;
  float phaseIncBase = avgFrequency[chan] / float(SAMPLERATE);

  for (int n = 0; n < NUM_HARMONICS; n++) {
    if (harmGain[n] <= 0.0f) continue; // don't bother computing silent harmonics

    float inc = phaseIncBase * float(n+1);
    harmPhase[chan][n] += inc;
    if (harmPhase[chan][n] >= 1.0f) harmPhase[chan][n] -= 1.0f;
    sum += getSineFromTable(harmPhase[chan][n]) * harmGain[n];
  }

  return sum;
}