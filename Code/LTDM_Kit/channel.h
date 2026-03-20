// channel.h
#ifndef CHANNEL_H
#define CHANNEL_H

#include "Arduino.h"
#include "system_config.h"

struct Channel {
    float fbGain;
    float adcScale;
    float noiseScale;
    int targetRMS;

    // Hardware parameters
    int adcPin;
    int polarityPin;
    int enablePin;

    // audio parameters
    volatile float in;          // normalised input signal -1.0 to 1.0
    volatile float out;         // normalised output signal -1.0 to 1.0
    volatile bool polarity;     // polarity of incoming signal
    
    uint64_t samples[N];
    volatile uint64_t measuredRMS;
    bool polsamples[N];
    volatile bool lastPolValue;
    bool activeDamp;
    uint16_t sampleIndex;
    uint64_t sampleSum;
};

#endif