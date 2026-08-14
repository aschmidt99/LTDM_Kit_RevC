# LTDM Kit Rev C

Firmware and hardware assets for a Teensy 4.1 based LTDM (Lorentz Time-Domain Multiplex) kit.

The intended workflow is:

1. Keep timing, PWM, sensing, and board plumbing stable.
2. Iterate quickly on behavior in `Code/LTDM_Kit/render.cpp`.
3. Map hardware controls (buttons/sliders/pedals) to your algorithm through the UI layer.

![VisualGuide](VisualGuide.jpg)

## Project Structure

- `Code/LTDM_Kit`: Teensy firmware source
- `Code/Python`: capture, analysis, and Audacity automation scripts
- `Electronics`: KiCad projects for board revisions
- `CAD`: mechanical STEP assets

Python tooling docs are in `Code/Python/README.md`.

## Program and Upload

### VS Code tasks (recommended)

Use `Cmd+Shift+P` -> `Tasks: Run Task` and select:

- `Teensy: Compile LTDM_Kit`
- `Teensy: Upload LTDM_Kit (prompt port)`
- `Teensy: Upload LTDM_Kit (auto port)`
- `Teensy: Compile + Upload LTDM_Kit (auto port)`

Task definitions live in `.vscode/tasks.json`.

### Arduino CLI (direct)

```bash
cd Code/LTDM_Kit
arduino-cli compile --fqbn teensy:avr:teensy41 .
arduino-cli upload --fqbn teensy:avr:teensy41 -p /dev/cu.usbmodemXXXX .
```

## How the Firmware is Organized

- `LTDM_Kit.ino`: startup and top-level loop
- `flexpwm.*`: timing and ISR plumbing
- `render.cpp`: per-sample DSP/control law (primary customization file)
- `ui.cpp`: button/slider/pedal scan, LED feedback, serial text output
- `serialctrl.cpp`: optional serial override of UI controls
- `capture_stream.*`: deterministic capture trigger/stream output for measurement scripts
- `pinmap.h`: central pin assignments
- `context.h`: shared frame context passed to render code

At runtime, the flow is:

1. ISR acquires channel state and UI state into `context`.
2. `render(context)` computes output values once per sample.
3. PWM/sense outputs are driven from those computed values.

## Theory and Philosophy

This codebase intentionally separates three concerns:

1. Real-time infrastructure: sample timing, GPIO/PWM scheduling, ADC/sense capture.
2. Control surface: what knobs/buttons/pedals currently mean.
3. Algorithm: how measured input becomes actuation output.

The design goal is to let you innovate on behavior without destabilizing timing-critical plumbing.

In practice, treat `render.cpp` as your sandbox for algorithmic ideas:

- Feedback shaping
- Noise injection and excitation strategies
- RMS/energy targeting
- Harmonic synthesis
- Cross-channel coupling experiments

Keep UI semantics explicit and stable:

- Decide which control maps to which concept.
- Keep that mapping documented in comments and README.
- Avoid hiding control meaning across many files.

This gives you repeatable experiments: you can compare algorithm changes while holding hardware and timing constant.

## Where to Make Changes

### Audio/actuation behavior

Edit `Code/LTDM_Kit/render.cpp`.

Key entry points:

- `bool renderSetup(LorentzContext *context)` for one-time setup
- `void render(LorentzContext *context)` for per-sample behavior

Useful signals available from `context`:

- `context->ch[0].in`, `context->ch[1].in`
- `context->buttons[0..15]`
- `context->sliders[0..15]`
- `context->pedals[0..1]`

Typical edits:

- Change how target RMS, noise, and feedback gain combine.
- Add/remove dynamic limiting behavior.
- Adjust harmonic bank use and scaling.

### Button/slider behavior mapping

Edit `Code/LTDM_Kit/ui.cpp` and `Code/LTDM_Kit/render.cpp` together.

How it works:

1. `ui.cpp` scans physical mux inputs.
2. `sliderRemap` in `ui.cpp` maps physical control order to logical slider indices.
3. `render.cpp` assigns meaning to those logical indices.

If a slider or button feels "wrong", check `sliderRemap` first, then the index usage in `render.cpp`.

### Pin assignments

Edit `Code/LTDM_Kit/pinmap.h` only.

## Current Implementation (This Revision)

This is what the current firmware does by default.

### Top-level startup

In `Code/LTDM_Kit/LTDM_Kit.ino` setup currently initializes:

- UI scan + LEDs
- Servo attach
- FlexPWM and interrupts
- render setup
- sine table
- capture stream hooks

### Render/control behavior (channel 1 focused)

In `Code/LTDM_Kit/render.cpp`:

- Button 0 enables channel 1 output (`enablePin` high/low).
- Button 1 enables channel 2 output.
- Button 2 toggles RMS-targeted gain behavior for CH1.
- Button 6 gates CH1 noise injection.
- Button 8 requests capture start while capture is armed.

- Slider 0: CH1 feedback gain (`fbGain`).
- Slider 1: CH1 target RMS.
- Slider 2: noise update rate (acts like coarse smoothing on random term).
- Slider 3: CH1 noise scale.
- Slider 4: harmonic frequency smoothing parameter (`alpha`).
- Sliders 8..15: gains for harmonics 1..8 (`NUM_HARMONICS = 8`).

- Channel 2 currently carries visual-alias pulse output behavior (`renderLEDPulse(...)`) rather than the older noise/feedback block (that block remains commented out).

### LED/UI feedback

In `Code/LTDM_Kit/ui.cpp`:

- TLC5947 LEDs reflect enable/limit/target and measured RMS states.
- UI scan runs in two-phase mux read/write cycles.
- `output()` also prints debug telemetry over serial every ~100 ms when capture stream is idle.

### Servo status

Servo control is still active in this revision:

- Servo is attached in `initServo()`.
- Servo angle is driven in `updateServo()` from slider/button state.

If servo hardware is removed, remove servo include/object/init/update calls to simplify firmware and build dependencies.

### Serial override mode

`Code/LTDM_Kit/serialctrl.cpp` can override hardware controls via framed serial packets.

- Start marker: `255`
- End marker: `254`
- Payload: mode + 16 sliders + 16 buttons + 2 pedals

When override is active, incoming values are written directly into the shared UI state arrays.

## Notes for Future Cleanup

- `Code/LTDM_Kit/ui.h` currently declares `updateSevo()` (typo) while implementation is `updateServo()`.
- Servo support is still compiled in; consider a feature flag or full removal if no longer needed.