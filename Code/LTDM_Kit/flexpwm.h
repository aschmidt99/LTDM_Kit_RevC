// flexpwm.h
#ifndef FLEXPWM_H
#define FLEXPWM_H

#include <Arduino.h>
#include "system_config.h"
#include "pinmap.h"
#include "channel.h"
#include "context.h"

#define SM0_MASK (1 << 0) // FLEXPWM2_SM0 (Pins 4(A) and 33(B))
#define SM1_MASK (1 << 1) // FLEXPWM2_SM1 (Pins 5(A))
#define SM2_MASK (1 << 2) // FLEXPWM2_SM2 (Pins 6(A) and 9(B))
#define SM3_MASK (1 << 3) // FLEXPWM2_SM3 (Pin 36(A) and 37(B))

// Here we have a 2 channel system, but this could help with scaling to more channels if desired
// struct Channel {
//     // Config - things changed by UI
//     float fbGain;           // The gain of feedback (before considering any RMS limiting)
//     float adcScale;         // for scaling the above gain back when RMS limiting is implemented
//     float noiseScale;       // for scaling the noise back when a signal sensed
//     int targetRMS;          // the target RMS measurement

//     //for RMS calculation and Delay

//     // Pin assignments
//     int adcPin;
//     int polarityPin;
//     int enablePin;

//     // Runtime state
//     volatile uint64_t in;      // magnitude of incoming signal
//     uint64_t samples[N];    // store last N adc samples (in circular buffer) - for RMS limiting and noise actuation attenuation
//     volatile uint64_t measuredRMS;   // the current RMS measurement

//     volatile bool inPolValue;        // polaritiy of incoming signal
//     bool polsamples[N];     // store last N polarity samples (in circular buffer) - for harmonic synthesis and delay
    
//     volatile bool outPolValue;       // the polarity of the applied signal
//     volatile bool lastPolValue;      // for harmonic synthesis - though think this will be obsolete if I were to use the polSamples[N-1]???
//     float pulseWidth;                // length of applied signal (should this really be a float??)

//     bool activeDamp; // are we actively damping?

//     uint16_t sampleIndex;    // current position in circular buffer
//     uint64_t sampleSum;      // running sum of squares for efficient RMS
// };

extern int noise;
extern int deadZone;
extern volatile int count;
extern int maxPulseLength;
extern volatile uint16_t g_lastOutputPWMVal;

void initADC();
void initFlexPWM();
void setInterrupts();
void setOutputFrequency(float frequency);
void setOutputPWM(uint16_t val);

#endif