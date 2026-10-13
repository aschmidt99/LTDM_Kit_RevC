// render.cpp
#include "render.h"
#include "Arduino.h"

// float fbGain;
// float adcScale;
// float noiseScale;
// float targetRMS;


 static inline Lfloat LEAF_clip(Lfloat min, Lfloat val, Lfloat max)

{

    if (val < min)
    {
        return min;
    }
    else if (val > max)
    {
        return max;
    }
    else
    {
        return val;
    }
}

// Less efficient, more accurate version of SVF, in which cutoff frequency is
// taken as Lfloating point Hz value and tanf is calculated when frequency changes.
void tSVF_init (tSVF *const svff, SVFType type, Lfloat freq, Lfloat Q)
{
    tSVF_initToPool(svff, type, freq, Q);
    // or maybe this?
    /*
     * hp=1 bp=A/Q (where A is 10^(G/40) and G is gain in decibels) and lp = 1
     */
}

void tSVF_initToPool (tSVF *const svff, SVFType type, Lfloat freq, Lfloat Q)
{
   
    _tSVF *svf = *svff = (_tSVF *) malloc(sizeof(_tSVF));

    svf->sampleRate = SAMPLERATE;
    svf->invSampleRate = 1.0f/SAMPLERATE;
    svf->sampleRatio = 48000.0f / svf->sampleRate;
    svf->type = type;

    svf->ic1eq = 0.0f;
    svf->ic2eq = 0.0f;
    svf->Q = Q;
    svf->cutoff = freq;
    svf->g = tanf(PI * freq * svf->invSampleRate);
    svf->k = 1.0f / Q;
    svf->a1 = 1.0f / (1.0f + svf->g * (svf->g + svf->k));
    svf->a2 = svf->g * svf->a1;
    svf->a3 = svf->g * svf->a2;

    svf->cH = 0.0f;
    svf->cB = 0.0f;
    svf->cBK = 0.0f;
    svf->cL = 1.0f;

    if (type == SVFTypeLowpass) {
        svf->cH = 0.0f;
        svf->cB = 0.0f;
        svf->cBK = 0.0f;
        svf->cL = 1.0f;
    } else if (type == SVFTypeBandpass) {
        svf->cH = 0.0f;
        svf->cB = 1.0f;
        svf->cBK = 0.0f;
        svf->cL = 0.0f;
    } else if (type == SVFTypeHighpass) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = -1.0f;
    } else if (type == SVFTypeNotch) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = 0.0f;
    } else if (type == SVFTypePeak) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = -2.0f;
    }
}

void tSVF_free (tSVF *const svff)
{

}

Lfloat tSVF_tick (tSVF const svf, Lfloat v0)
{
    Lfloat v1, v2, v3;
    v3 = v0 - svf->ic2eq;
    v1 = (svf->a1 * svf->ic1eq) + (svf->a2 * v3);
    v2 = svf->ic2eq + (svf->a2 * svf->ic1eq) + (svf->a3 * v3);
    svf->ic1eq = (2.0f * v1) - svf->ic1eq;
    svf->ic2eq = (2.0f * v2) - svf->ic2eq;

    return (v0 * svf->cH) + (v1 * svf->cB) + (svf->k * v1 * svf->cBK) +
            (v2 * svf->cL);
}

Lfloat tSVF_tickHP (tSVF const svf, Lfloat v0)
{
    Lfloat v1, v2;
    v1 = svf->a1 * svf->ic1eq + svf->a2 * (v0 - svf->ic2eq);
    v2 = svf->ic2eq + svf->g * v1;
    svf->ic1eq = (2.0f * v1) - svf->ic1eq;
    svf->ic2eq = (2.0f * v2) - svf->ic2eq;
    return v0 - (svf->k * v1) - (v2);
}

Lfloat tSVF_tickBP (tSVF const svf, Lfloat v0)
{
    Lfloat v1, v2;
    v1 = svf->a1 * svf->ic1eq + svf->a2 * (v0 - svf->ic2eq);
    v2 = svf->ic2eq + svf->g * v1;
    svf->ic1eq = (2.0f * v1) - svf->ic1eq;
    svf->ic2eq = (2.0f * v2) - svf->ic2eq;

    return v1;
}

Lfloat tSVF_tickLP (tSVF const svf, Lfloat v0)
{
    Lfloat v1, v2;
    v1 = svf->a1 * svf->ic1eq + svf->a2 * (v0 - svf->ic2eq);
    v2 = svf->ic2eq + svf->g * v1;
    svf->ic1eq = (2.0f * v1) - svf->ic1eq;
    svf->ic2eq = (2.0f * v2) - svf->ic2eq;
    return v2;
}

void tSVF_setFreq (tSVF const svf, Lfloat freq)
{
    svf->cutoff = LEAF_clip(0.0f, freq, svf->sampleRate * 0.5f);
    svf->g = tanf(PI * svf->cutoff * svf->invSampleRate);
    svf->a1 = 1.0f / (1.0f + svf->g * (svf->g + svf->k));
    svf->a2 = svf->g * svf->a1;
    svf->a3 = svf->g * svf->a2;
}


void tSVF_setQ (tSVF const svf, Lfloat Q)
{
    svf->Q = Q;
    svf->k = 1.0f / Q;

    svf->a1 = 1.0f / (1.0f + svf->g * (svf->g + svf->k));
    svf->a2 = svf->g * svf->a1;
    svf->a3 = svf->g * svf->a2;
}

void tSVF_setFreqAndQ (tSVF const svf, Lfloat freq, Lfloat Q)
{
    svf->cutoff = LEAF_clip(0.0f, freq, svf->sampleRate * 0.5f);
    svf->k = 1.0f / Q;
    svf->g = tanf(PI * svf->cutoff * svf->invSampleRate);
    svf->a1 = 1.0f / (1.0f + svf->g * (svf->g + svf->k));
    svf->a2 = svf->g * svf->a1;
    svf->a3 = svf->g * svf->a2;
}

void tSVF_setFilterType (tSVF const svf, SVFType type)
{
    if (type == SVFTypeLowpass) {
        svf->cH = 0.0f;
        svf->cB = 0.0f;
        svf->cBK = 0.0f;
        svf->cL = 1.0f;
    } else if (type == SVFTypeBandpass) {
        svf->cH = 0.0f;
        svf->cB = 1.0f;
        svf->cBK = 0.0f;
        svf->cL = 0.0f;
    } else if (type == SVFTypeHighpass) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = -1.0f;
    } else if (type == SVFTypeNotch) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = 0.0f;
    } else if (type == SVFTypePeak) {
        svf->cH = 1.0f;
        svf->cB = 0.0f;
        svf->cBK = -1.0f;
        svf->cL = -2.0f;
    }
}

void tSVF_setSampleRate (tSVF const svf, Lfloat sr)
{
    svf->sampleRate = sr;
    svf->invSampleRate = 1.0f / svf->sampleRate;
    svf->sampleRatio = 48000.0f / svf->sampleRate;

}


static inline Lfloat LEAF_midiToFrequency(Lfloat f)
{
    if( f <= -1500.0f ) return (0);
    else if( f > 1499.0f ) return (LEAF_midiToFrequency(1499.0f));
    else return ( powf(2.0f, (f - 69.0f) * 0.083333333333333f) * 440.0f );
}



tSVF myBandpass;
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
// one-time initialisation
bool renderSetup(LorentzContext *context) {
    invNumSamples = 1.0f / (float)numSamples;
    tSVF_init(&myBandpass, SVFTypeBandpass, 1000.0f, 0.6f);
    return true;
}

// called once per sample
void render(LorentzContext *context) {

    uint32_t start = ARM_DWT_CYCCNT;

   #if 0
    uint32_t attack = 0;

    float amplitude = (fabsf(context->ch[0].in));
    if (amplitude > 0.01f)
    {
      attack = 1;
    }
    else
    {
      attack = 0;
    }


    currentSign = (context->ch[0].in > 0.0f);
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
    sum0 -= buffer0[sampleIndex] * buffer0[sampleIndex];
    buffer0[sampleIndex] = fabs(context->ch[0].in);
    sum0 += fabs(context->ch[0].in) * fabs(context->ch[0].in);

    // CH2 RMS Calculation
    sum1 -= buffer1[sampleIndex] * buffer1[sampleIndex];
    buffer1[sampleIndex] = fabs(context->ch[1].in);
    sum1 += fabs(context->ch[1].in) * fabs(context->ch[1].in);

    sampleIndex = (sampleIndex + 1) % numSamples;

    volatile int nanChecker = 0;
    inputSum = (float)sum0;
    currRMS0 = sqrt((float)sum0 * invNumSamples);
    if (isnan(currRMS0))
    {
      context->ch[0].measuredRMS = 0.0;
    }
    else
    {
        context->ch[0].measuredRMS = currRMS0;
    }

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

    if (currRMS0 > 0.1f)
    {
      noiseOnOff = 0.0f;
    }
    else
    {
      noiseOnOff = 1.0f;
    }
    float noiseFactor0 = (noise0 * constrain((noiseOnOff), 0.0f, 1.0f) * targetRMS0);
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

    myFreq = LEAF_midiToFrequency(context->sliders[8] * 127.0f);
    tSVF_setFreq(myBandpass, myFreq);
    float myQScaling = context->sliders[10] * 50.0f;
    float myQ = context->sliders[9]*myQScaling + 0.5f;
    tSVF_setQ(myBandpass, myQ);
    float gainComp =  1.0f / myQ;


    context->ch[0].out = tSVF_tick(myBandpass, (context->ch[0].in  * gainComp * fbFactor0  + noiseFactor0));// * float(context->buttons[6]));

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