// render.cpp
#include "render.h"
#include "Arduino.h"
#include "leaf.h"

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


uint32_t currentSign = 0;
uint32_t previousSign = 0;
uint32_t periodCounter = 0;
uint32_t halfPeriod = 0;
uint32_t signSwitchInt = 0;
uint32_t previousAttack = 0;
uint32_t frozenPeriod = 10;

tSVF myBandpass;
tSVF myBandpass2;
tAllpass myAllpass;
LEAF leaf;
#define LEAF_MEM_SIZE 10000 //
char leafMem[LEAF_MEM_SIZE];

// one-time initialisation
bool renderSetup(LorentzContext *context) {
    LEAF_init(&leaf, SAMPLERATE, leafMem, LEAF_MEM_SIZE, rand());
    invNumSamples = 1.0f / (float)numSamples;
    tSVF_init(&myBandpass, SVFTypeBandpass, 1000.0f, 0.6f, &leaf);
    tSVF_init(&myBandpass2, SVFTypeBandpass, 200.0f, 0.6f, &leaf);
    tAllpass_init(&myAllpass, 0, 1000, &leaf);
    return true;
}

// called once per sample
void render(LorentzContext *context) {
float filteredIn = LEAF_clip(-1.0f, context->ch[0].in, 1.0f);
//float filteredIn = LEAF_clip(-1.0f, tSVF_tick(myBandpass, context->ch[0].in), 1.0f);
filteredIn = tAllpass_tick(myAllpass, filteredIn);


    uint32_t start = ARM_DWT_CYCCNT;

   #if 0
    uint32_t attack = 0;

    float amplitude = (fabsf(filteredIn));
    if (amplitude > 0.01f)
    {
      attack = 1;
    }
    else
    {
      attack = 0;
    }


    currentSign = (filteredIn.in > 0.0f);
    if (currentSign != previousSign)
    {
      context->ch[0].currentPeriod = periodCounter;
      halfPeriod = periodCounter >> 2;
      periodCounter = 0;
    }
    periodCounter++;
    previousSign = currentSign;
    if ((context->buttons[6]) == 0)
    //if ((attack == 1) && (previousAttack == 0))
    {
      frozenPeriod = halfPeriod;
    }

    previousAttack = attack;
#endif

    // only update noise pulse width every N frames - third knob now acts as a rudimentary LPF on the noise
    if ((context->frameCount % int(12 - context->sliders[2] * 12) == 0)) {noise0 = random(-1024, 1024)*0.00097656f;} //0.00097656 is 1/1024 (to avoid the divide)
    if ((context->frameCount % int(12 - context->sliders[6] * 12) == 0)) {noise1 = random(-1024, 1024)*0.00097656f;} //0.00097656 is 1/1024 (to avoid the divide)

    // CH1 RMS calculation

    sum0 -= buffer0[sampleIndex];
    buffer0[sampleIndex] = (fabs(filteredIn) * fabs(filteredIn));
    sum0 += buffer0[sampleIndex];

    // CH2 RMS Calculation
    sum1 -= buffer1[sampleIndex] * buffer1[sampleIndex];
    buffer1[sampleIndex] = fabs(context->ch[1].in);
    sum1 += fabs(context->ch[1].in) * fabs(context->ch[1].in);

    sampleIndex = (sampleIndex + 1) % numSamples;

    volatile int nanChecker = 0;
    if (sum0 < 0.001f)
    {
      sum0 = 0.001f;
    }
    inputSum = sum0;


    currRMS0 = sqrt(sum0 * invNumSamples);

    context->ch[0].measuredRMS = currRMS0;
    

    currRMS1 = sqrt((float)sum1 * invNumSamples);
    if (isnan(currRMS1))
    {
      context->ch[1].measuredRMS = 0.0;
    }
    else
    {
        context->ch[1].measuredRMS = currRMS1;
    }
    
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

    float noiseOnOff = 0.0f;
    float noiseThresh = context->sliders[11] * 0.08f;
    if (currRMS0 > noiseThresh)
    {
      noiseOnOff = 0.0f;
    }
    else
    {
      noiseOnOff = 1.0f;
    }
    float noiseFactor0 = (noise0 * constrain((noiseOnOff), 0.0f, 1.0f) * targetRMS0);
   noiseFactor0 = tSVF_tick(myBandpass2, noiseFactor0);
    //float noiseFactor0 = (noise0 * constrain((context->ch[0].noiseScale - currRMS0), 0.0f, 1.0f) * targetRMS0);
    float fbFactor0 =  context->ch[0].fbGain * ((3.0f * (targetRMS0 - currRMS0)*float(context->buttons[2])) +  1.0*!(context->buttons[2]));

#if 0
    if (periodCounter > frozenPeriod)
    signSwitchInt = !signSwitchInt;
    float signSwitch = (float)signSwitchInt;
    signSwitch *= 2.0f;
    signSwitch -= 1.0f;
    float signSwitchFactor0 =  (signSwitch*(context->buttons[6])) +  (1.0*!(context->buttons[6]));
#endif
    

    // apply input + noise to output

    myFreq = LEAF_midiToFrequency(context->pedals[1] * 127.0f);
    tSVF_setFreq(myBandpass, myFreq);
    tSVF_setFreq(myBandpass2, myFreq);
    //float myQScaling = context->sliders[10] * 50.0f;
    myQ = context->pedals[0] + 1.0f;
    tSVF_setQ(myBandpass, myQ);
    tSVF_setQ(myBandpass2, .3f);
    float gainComp =  1.0f / myQ;
    //float gainComp = 100.0f;

    context->ch[0].out = (filteredIn  * gainComp * fbFactor0  + noiseFactor0);// * float(context->buttons[6]));

    #if 0
    if (context->sliders[8] > 0.5f)
    {
      myFreq = 168.0f;
    }
    else
    {
      myFreq = 260.0f;
    }
    #endif
    
    tAllpass_setDelay(myAllpass, 200.0f*context->sliders[8]*currRMS0);

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