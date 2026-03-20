// context.h
#ifndef CONTEXT_H
#define CONTEXT_H

#include "system_config.h"
#include "channel.h"

struct LorentzContext {
    // INPUTS - populated by the ISR before render() is called
    Channel ch[2];

    // Hardware inputs
    bool  buttons[16];       // all button states
    float sliders[16];       // all slider/pot values, normalised 0.0-1.0
    float pedals[2];     // both expression pedal values

    // SYSTEM INFO - set once at init, read-only in render()
    float sampleRate;
    // int   bufferSize;        // always 1 for your sample-by-sample system
    // unsigned long long frameCount; // total samples elapsed, useful for LFOs etc.
};

extern LorentzContext context;

#endif