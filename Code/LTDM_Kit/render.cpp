// render.cpp
#include "render.h"
#include "Arduino.h"

// one-time initialisation
bool renderSetup(LorentzContext *context) {
    return true;
}

// called once per sample
void render(LorentzContext *context) {
    
    // Enable channel 1 with leftmost latching button
    digitalWrite(context->ch[0].enablePin, context->buttons[0]);

    // feedback gain controlled by knob 0 (range is 0.-4.)
    context->ch[0].fbGain = context->sliders[0];

    // apply input to output
    context->ch[0].out = (context->ch[0].in * context->ch[0].fbGain);

    // context->audioOut[1] = fabs(context->audioIn[1] * context->sliders[4] * 4.0f * (2.0f * float(context->polarity[1]) - 1.0f));
}