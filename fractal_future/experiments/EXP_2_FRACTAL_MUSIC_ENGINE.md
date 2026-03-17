# FRACTAL FUTURE — Experiment 2: Fractal Music Engine

ID: FF-EXP-002
Track: Generative Aesthetics Engine / Human Resonance Lab
Status: Design
Gate: FF-2 (Observation)
Evidence Target: E2 → E3

## Hypothesis
Music composed using fractal timing structures, harmonic ratios derived from sacred geometry, and self-similar melodic patterns will be perceived as more emotionally resonant and aesthetically pleasing than randomly generated or rigidly structured compositions of equivalent complexity.

## Background
- 1/f noise (pink noise) has fractal spectral properties and is found in music humans prefer (Voss & Clarke, 1975)
- Fractal dimension of music correlates with perceived complexity and beauty
- Sacred geometry ratios (phi, octave relationships) appear in classical composition
- Generative music systems can enforce structural constraints algorithmically

## Protocol

### Phase 1 — Engine Design (Weeks 1–2)
1. Build a Python-based generative music engine
2. Implement three generation modes:
   - **Random**: Notes and timing from uniform random distribution
   - **Grid**: Fixed tempo, fixed scale, repetitive patterns
   - **Fractal**: Self-similar timing (L-system or fractal subdivision), phi-based intervals, recursive melodic motifs
3. Constrain all three modes to same key, tempo range, and duration

### Phase 2 — Generation (Week 3)
1. Generate 10 compositions per mode (30 total)
2. Normalize volume, duration (60 seconds each), and instrumentation
3. Export as audio files (MIDI → synthesized WAV)

### Phase 3 — Blind Evaluation (Weeks 4–5)
1. Create blind listening test (randomized order, no labels)
2. Recruit 10+ listeners (friends, community, online)
3. Rate each clip on:
   - Pleasantness (1–10)
   - Emotional resonance (1–10)
   - Complexity perception (1–10)
   - "Would listen again" (Y/N)
4. Optional: Measure physiological response (HRV, GSR) if equipment available

### Phase 4 — Analysis (Week 6)
1. Compare ratings across three modes
2. Correlate fractal dimension of each clip with listener ratings
3. Identify specific fractal features that drive preference

## Variables
| Variable | Type | Measurement |
|----------|------|-------------|
| Generation mode | Independent | Random / Grid / Fractal |
| Listener ratings | Dependent | 1–10 scales + Y/N |
| Fractal dimension | Measured | Box-counting or spectral analysis |
| Duration | Controlled | 60 seconds each |
| Instrumentation | Controlled | Same synth patch |

## Technical Stack
- Python (midiutil, music21, or pretty_midi)
- L-system or IFS for fractal pattern generation
- FluidSynth or similar for MIDI→audio
- Jupyter notebook for analysis
- Google Forms or similar for blind listening test

## Success Criteria
- Fractal mode rated ≥1.5 points higher on pleasantness than random
- Fractal mode rated ≥1.0 points higher on emotional resonance than grid
- ≥60% of listeners prefer fractal clips in "would listen again"

## Entropy Controls
- Max time investment: 20 hours total (engine + generation + evaluation + analysis)
- Kill condition: If engine cannot produce listenable output after 10 hours, simplify scope
- Blast radius: No external system dependencies; all local

## Doctrine Alignment
- P1: Scale coherence (music must be coherent across beat, bar, phrase, section)
- P2: Recursive learning (engine iterates based on listener feedback)
- P5: Resonance over control (fractal emergence vs rigid composition)
- P6: Regeneration (generative system creates infinite variations)
