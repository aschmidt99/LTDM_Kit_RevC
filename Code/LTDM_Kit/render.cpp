// render.cpp
#include "render.h"
#include "Arduino.h"

// float fbGain;
// float adcScale;
// float noiseScale;
// float targetRMS;

const int numSamples = 200;
float invNumSamples = 1.0f;
float buffer0[numSamples] = {};
float buffer1[numSamples] = {};
float sum0 = 0.0f;
float sum1 = 0.0f;
extern float currRMS0 = 0.0f;
extern float currRMS1 = 0.0f;
extern float targetRMS0 = 0.0f;
extern float targetRMS1 = 0.0f;

int sampleIndex = 0;
float noise0 = 0.0f;
float noise1 = 0.0f;


// one-time initialisation
bool renderSetup(LorentzContext *context) {
    invNumSamples = 1.0f / (float)numSamples;
    return true;
}

// called once per sample
void render(LorentzContext *context) {

    uint32_t start = ARM_DWT_CYCCNT;
    // only update noise pulse width every N frames - third knob now acts as a rudimentary LPF on the noise
    if ((context->frameCount % int(12 - context->sliders[2] * 12) == 0)) {noise0 = random(-1024, 1024)*0.00097656f;} //0.00097656 is 1/1024 (to avoid the divide)
    if ((context->frameCount % int(12 - context->sliders[6] * 12) == 0)) {noise1 = random(-1024, 1024)*0.00097656f;} //0.00097656 is 1/1024 (to avoid the divide)

    // CH1 RMS calculation
    sum0 -= buffer0[sampleIndex] * buffer0[sampleIndex];
    buffer0[sampleIndex] = fabs(context->ch[0].in);
    sum0 += fabs(context->ch[0].in) * fabs(context->ch[0].in);

    // CH2 RMS Calculation
    sum1 -= buffer1[sampleIndex] * buffer1[sampleIndex];
    buffer1[sampleIndex] = fabs(context->ch[1].in);
    sum1 += fabs(context->ch[1].in) * fabs(context->ch[1].in);

    sampleIndex = (sampleIndex + 1) % numSamples;

    currRMS0 = sqrt((float)sum0 * invNumSamples);
    context->ch[0].measuredRMS = currRMS0;

    currRMS1 = sqrt((float)sum1 * invNumSamples);
    context->ch[1].measuredRMS = currRMS1;
    
    // Enable channel 1 with leftmost latching button (channel enable pin must be high)
    digitalWrite(context->ch[0].enablePin, context->buttons[0]);
    // Enable channel 2 with leftmost latching button (channel enable pin must be high)
    digitalWrite(context->ch[1].enablePin, context->buttons[1]);

    // Ch1 gain and noise stuff
    context->ch[0].fbGain = context->sliders[0];            // feedback gain controlled by knob 0
    context->ch[0].noiseScale = context->sliders[3];
		// context->ch[0].noiseScale = context->pedals[1];
    float targetRMS0 = context->sliders[1];         // the targetRMS
    context->ch[0].targetRMS = targetRMS0;
    // float targetRMS = context->pedals[0];

    float noiseFactor0 = (noise0 * constrain((context->ch[0].noiseScale - currRMS0), 0.0f, 1.0f) * targetRMS0);
    float fbFactor0 =  context->ch[0].fbGain * ((3.0f * (targetRMS0 - currRMS0)*float(context->buttons[2])) +  1.0*!(context->buttons[2]));

    // apply input + noise to output
    context->ch[0].out = context->ch[0].in * fbFactor0 + noiseFactor0 * float(context->buttons[6]);
    // context->audioOut[1] = fabs(context->audioIn[1] * context->sliders[4] * 4.0f * (2.0f * float(context->polarity[1]) - 1.0f));

    // Ch2 gain and noise stuff
    context->ch[1].fbGain = context->sliders[4];            // feedback gain controlled by knob 0
    context->ch[1].noiseScale = context->sliders[7];
		// context->ch[0].noiseScale = context->pedals[1];
    float targetRMS1 = context->sliders[5];         // the targetRMS
    context->ch[1].targetRMS = targetRMS1;
    // float targetRMS = context->pedals[0];

    float noiseFactor1 = (noise1 * constrain((context->ch[1].noiseScale - currRMS1), 0.0f, 1.0f) * targetRMS1);
    float fbFactor1 =  context->ch[1].fbGain * ((3.0f * (targetRMS1 - currRMS1)*float(context->buttons[3])) +  1.0*!(context->buttons[3]));

    // apply input + noise to output
    context->ch[1].out = context->ch[1].in * fbFactor1 + noiseFactor1 * float(context->buttons[7]);
    // context->audioOut[1] = fabs(context->audioIn[1] * context->sliders[4] * 4.0f * (2.0f * float(context->polarity[1]) - 1.0f));
    context->renderCycleCount = ARM_DWT_CYCCNT - start;
}