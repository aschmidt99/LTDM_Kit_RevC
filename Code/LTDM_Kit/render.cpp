// render.cpp
#include "render.h"
#include "Arduino.h"

// one-time initialisation
bool renderSetup(LorentzContext *context) {
    return true;
}

// called once per sample
void render(LorentzContext *context) {
    
    // Enable channel 1 with leftmost latching button (channel enable pin must be high)
    digitalWrite(context->ch[0].enablePin, context->buttons[0]);

    // feedback gain controlled by knob 0
    context->ch[0].fbGain = context->sliders[0];

    // apply input to output
    context->ch[0].out = (context->ch[0].in * context->ch[0].fbGain);

    // context->audioOut[1] = fabs(context->audioIn[1] * context->sliders[4] * 4.0f * (2.0f * float(context->polarity[1]) - 1.0f));
}

// the code below is the noise + rms limiing scheme that I am hoping to reinstate in here as an example

  // CHANNEL 1 ////////////////
  // CH1.outPolValue = CH1.inPolValue; // at least initially, we apply the same polarity to the output as comes in the input
  // // float pulseWidth = (CH1_adcValue*fbGain/4.0)*(2.0f*float(CH1_polValue) - 1.0f) + dutyHarmonic; // comment back in when ready for harmonic synthesis :)
  // CH1.pulseWidth = CH1.adcScale*(CH1.adcValue*CH1.fbGain/4.0)*(2.0f*float(CH1.inPolValue) - 1.0f) + noise*CH1.noiseScale; // + dutyHarmonic;
  // if (CH1.activeDamp){CH1.pulseWidth = CH1.adcValue*CH1.fbGain*CH1.inPolValue;} // active damp???    

  // // if summmed wave magnitued is negative, actuate other NFET.
  // if (CH1.pulseWidth < 0.0f) { 
  //   CH1.outPolValue = 0;
  // } else {
  //   CH1.outPolValue = 1;
  //  }
  
  // CH1.pulseWidth = fabs(CH1.pulseWidth); // rectify pulse value (for when added noise or synthesized harmonic flips polarity of output

  // // max pulse length check - will need to be smaller than this later.
  // if (CH1.pulseWidth > FLEXPWM2_SM2VAL1*0.6) CH1.pulseWidth= FLEXPWM2_SM2VAL1*0.6;  // I'm worried this is a bit stupid, but for now the sense pulse cannot exceed the total period of one window

  // // CHANNEL 2 /////////////////
  // CH2.outPolValue = CH2.inPolValue; // we apply the same polarity to the output as comes in the input (for basic infinite sustain)
  // // float pulseWidth = (CH1_adcValue*fbGain/4.0)*(2.0f*float(CH1_polValue) - 1.0f) + dutyHarmonic; // comment back in when ready for harmonic synthesis :)
  // CH2.pulseWidth = CH2.adcScale*(CH2.adcValue*CH2.fbGain/4.0)*(2.0f*float(CH2.inPolValue) - 1.0f) + noise*CH2.noiseScale; // + dutyHarmonic;
  //     if (CH2.activeDamp){CH2.pulseWidth = CH2.adcValue*CH2.fbGain*CH2.inPolValue;} // active damp???
      
  // // if summmed wave magnitued is negative, actuate other NFET.
  // if (CH2.pulseWidth < 0.0f) { 
  //   CH2.outPolValue = 0;
  // } else {
  //   CH2.outPolValue = 1;
  //  }
  
  // CH2.pulseWidth = fabs(CH2.pulseWidth); // rectify pulse value

  // // max pulse length check - will need to be smaller than this later.
  // if (CH2.pulseWidth > FLEXPWM2_SM2VAL1*0.5) CH2.pulseWidth = FLEXPWM2_SM2VAL1*0.5;  // I'm worried this is a bit stupid, but for now the sense pulse cannot exceed the total period of one window
