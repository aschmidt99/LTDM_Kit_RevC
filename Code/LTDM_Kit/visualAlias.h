// visualAlias.h

// use Channel 2 to drive an LED phase-locked to Channel 1's tracked fundamental frequency
// inspired by Slow Dance by Jeff Lieberman


// knob 6 -> threshold of comparator
// knob 7 -> freq offset

#ifndef VISUALALIAS_H
#define VISUALALIAS_H

#include <Arduino.h>

extern float ledPhase; // running phase 0.0-1.0 for the LED pulse oscillator

// Once per sample.

// threshold sets comparator level: < threshold, LED OFF, > threshold, LED ON
float renderLEDPulse(float freqHz, float freqOffsetHz, float threshold, float phaseOffset);

#endif