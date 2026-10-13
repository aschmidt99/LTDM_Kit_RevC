// render.h
#ifndef RENDER_H
#define RENDER_H

#define Lfloat float
#include "ui.h"
#include "context.h"

    typedef enum SVFType
    {
        SVFTypeHighpass = 0,
        SVFTypeLowpass,
        SVFTypeBandpass,
        SVFTypeNotch,
        SVFTypePeak,
        SVFTypeLowShelf,
        SVFTypeHighShelf
    } SVFType;

typedef struct _tSVF
    {
        SVFType type;
        Lfloat cutoff, Q, cutoffMIDI;
        Lfloat ic1eq,ic2eq;
        Lfloat g,k,a1,a2,a3,cH,cB,cL,cBK;
        Lfloat sampleRate;
        Lfloat invSampleRate;
        Lfloat phaseComp;
        Lfloat sampleRatio;
    } _tSVF;
    
    typedef _tSVF* tSVF;

    // Memory handlers for `tSVF`
    void    tSVF_init                (tSVF* const, SVFType type, Lfloat freq, Lfloat Q);
    void    tSVF_initToPool          (tSVF* const, SVFType type, Lfloat freq, Lfloat Q);
    void    tSVF_free                (tSVF* const);

    // Tick functions for `tSVF`
    Lfloat  tSVF_tick                (tSVF const, Lfloat v0);
    Lfloat  tSVF_tickLP              (tSVF const, Lfloat v0);
    Lfloat  tSVF_tickHP              (tSVF const, Lfloat v0);
    Lfloat  tSVF_tickBP              (tSVF const, Lfloat v0);

    // Setter functions for `tSVF`
    void tSVF_setFilterType (tSVF const svf, SVFType type);
    void    tSVF_setFreq             (tSVF const, Lfloat freq);
    void    tSVF_setQ                (tSVF const, Lfloat Q);
    void    tSVF_setFreqAndQ         (tSVF const svff, Lfloat freq, Lfloat Q);
    void    tSVF_setSampleRate       (tSVF const svff, Lfloat sr);

// Called once at startup
bool renderSetup(LorentzContext *context);

// Called once per sample - user writes DSP and control logic here
void render(LorentzContext *context);
extern uint32_t frozenPeriod;
#endif