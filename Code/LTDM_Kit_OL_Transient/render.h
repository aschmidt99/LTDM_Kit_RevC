// render.h
#ifndef RENDER_H
#define RENDER_H

#include "context.h"

// Called once at startup
bool renderSetup(LorentzContext *context);

// Called once per sample - user writes DSP and control logic here
void render(LorentzContext *context);

#endif