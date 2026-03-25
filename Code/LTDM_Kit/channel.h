// channel.h
#ifndef CHANNEL_H
#define CHANNEL_H

#include "Arduino.h"
#include "system_config.h"

struct Channel {
    float fbGain;               // amount of feedback to put back onto channel
    float adcScale;             // used for scaling back feedback when target RMS is achieved
    float noiseScale;           // amount of noise to put through channel
    float targetRMS;            // the target RMS level (normalized to 0.0f-1.0f)

    // Hardware pins
    const int adcPin;
    const int polarityPin;
    const int enablePin;

    // audio parameters
    volatile float in;          // normalised input signal -1.0 to 1.0
    volatile float out;         // normalised output signal -1.0 to 1.0
    
    uint64_t samples[bufferLength];
    volatile uint64_t measuredRMS;
    volatile bool lastPolValue;
    bool activeDamp;
    uint16_t sampleIndex;
    uint64_t sampleSum;
};

#endif