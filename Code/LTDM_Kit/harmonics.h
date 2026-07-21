// harmonics.h

// additive harmomic synthesis. Locks to a channel's estimated fundamental frequency
// via zero-cross detection.

// Sliders set gain of each harmonic. Each channel

#ifndef HARMONICS_H
#define HARMONICS_H

#include <Arduino.h>

#define NUM_HARMONICS 8
#define NUM_CHANNELS  2

// for frequency estimate
extern float alpha; //smoothing factor for fundamental freq estimation
extern float avgFrequency[NUM_CHANNELS]; // smoothed frequency estimation (Hz)
extern volatile uint32_t lastZeroCrossTime[NUM_CHANNELS]; //
extern volatile float fundamentalFreq[NUM_CHANNELS]; // instantaneous freq estimation (Hz)

// Harmonic oscillator bank
extern float harmPhase[NUM_CHANNELS][NUM_HARMONICS]; // running phase 0.-1.
extern float harmGain[NUM_HARMONICS];                // 0.0-1.0 gain, per harmonic

// Smooths instantaneous freq measurement into average
void updateAvgFrequency(int chan, float frequency);

// Call once per sample per channel with that channel's current polarity state
// (e.g. context->ch[chan].in >= 0). Detects rising edges to estimate pitch.
void updateHarmonicPitch(int chan, bool polarityHigh);

// Call once per sample per channel. Advances all 8 phase accumulators for
// this channel at multiples of its tracked fundamental and returns the
// gain-weighted sum, normalized to roughly -1.0..1.0.
float renderHarmonics(int chan);

#endif