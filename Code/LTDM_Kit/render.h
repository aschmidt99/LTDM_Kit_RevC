// render.h
#ifndef RENDER_H
#define RENDER_H

#define Lfloat float
#include "ui.h"
#include "context.h"

#include "leaf.h"
   

// Called once at startup
bool renderSetup(LorentzContext *context);

// Called once per sample - user writes DSP and control logic here
void render(LorentzContext *context);
extern uint32_t frozenPeriod;
#endif