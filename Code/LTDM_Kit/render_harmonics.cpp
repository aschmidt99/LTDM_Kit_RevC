// // render.cpp
// #include "render.h"
// #include "Arduino.h"
// #include "SineTable.h"
// #include "harmonics.h"

// // float fbGain;
// // float adcScale;
// // float noiseScale;
// // float targetRMS;

// const int numSamples = 200;
// float buffer[numSamples] = {};
// float sum = 0.0f;
// float currRMS = 0.0f;
// float targetRMS = 0.0f;
// int sampleIndex = 0;

// float noise = 0.0f;
// float sineScale = 0.0f;

// // one-time initialisation
// bool renderSetup(LorentzContext *context) {
//     return true;
// }

// // called once per sample
// void render(LorentzContext *context) {

//     // only update noise pulse width every N frames - third knob now acts as a rudimentary LPF on the noise
//     if ((context->frameCount % int(12 - context->sliders[2] * 12) == 0)) {noise = random(-1024, 1024)/1024.0f;}

//     // RMS calculation
//     sum -= buffer[sampleIndex] * buffer[sampleIndex];
//     buffer[sampleIndex] = fabs(context->ch[0].in);
//     sum += fabs(context->ch[0].in) * fabs(context->ch[0].in);

//     sampleIndex = (sampleIndex + 1) % numSamples;

//     currRMS = sqrt((float)sum / (float)numSamples);
//     context->ch[0].measuredRMS = currRMS;
    
//     // Enable channel 1 with leftmost latching button (channel enable pin must be high)
//     digitalWrite(context->ch[0].enablePin, context->buttons[0]);

//     context->ch[0].fbGain = context->sliders[0];            // feedback gain controlled by knob 0
//     // context->ch[0].noiseScale = context->sliders[3];
// 		// context->ch[0].noiseScale = context->pedals[1];
// 		sineScale = context->pedals[1];

//     float targetRMS = context->sliders[1];         // the targetRMS
//     // float targetRMS = context->pedals[0];

//     float noiseFactor = (noise * constrain((context->ch[0].noiseScale - currRMS), 0.0f, 1.0f) * targetRMS);
//     float fbFactor =  context->ch[0].fbGain * 3.0f * (targetRMS - currRMS);

// 		// arbitrary sine wave??
// 		phaseIncBase = (context->pedals[0]*2000.0f) / float(SAMPLERATE);      // base freq increment at 20kHz PWM
    
//     // Arbitrary frequency handlings
//     phaseIncNth = phaseIncBase;              // Nth
//     phaseNth += phaseIncNth;
//     if (phaseNth >= 1.0f) phaseNth -= 1.0f;

// 		float sineVal = getSineFromTable(phaseNth);
//     // float harmonicVal3rd = getSineFromTable(adjustedPhase3rd);
//     // float harmonicVal5th = getSineFromTable(adjustedPhase5th);
//     // float harmonicVal7th = getSineFromTable(adjustedPhase7th);
//     // dutyHarmonic = harmonicVal3rd * harmGain3rd + harmonicVal5th * harmGain5th + harmonicVal7th * harmGain7th + harmonicValNth * harmGainNth;
//     // dutyHarmonic = harmonicValNth * noise;

// 		float sineWaveFactor = sineVal * sineScale;

//     // apply input + noise to output
//     context->ch[0].out = context->ch[0].in * fbFactor + sineWaveFactor;    
//     // context->audioOut[1] = fabs(context->audioIn[1] * context->sliders[4] * 4.0f * (2.0f * float(context->polarity[1]) - 1.0f));

//     // very basic feedback for channel 2
//     context->ch[1].out = context->ch[1].in * context->sliders[4];
// }