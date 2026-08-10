# eprsynth-proto
concatenative synthesizer based on the og papers that led to vocaloid 1. vibecoded with qwen3.8-max...
---
Based on the provided papers (**SMAC-03** for SPP/Concatenation, **ICMC-01** for EpR/Excitation) and the **VOCALOID-1 Architecture Diagram** (User Controls/MicroScore), here is the comprehensive status table of the implementation.

**Legend:**
*   ✅ **Implemented**: Fully functional in the current codebase.
*   🟡 **In Progress / Approximate**: Implemented with a simplified or alternative method (e.g., parametric instead of SPP, noise-floor instead of inverse-filtered residual).
*   ⚪ **Missing**: Not yet implemented.

### 1. Core Synthesis Engine (EpR & Excitation)
*References: ICMC-01 §3, SMAC-03 §3*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **SMS Analysis Front-end** (STFT + Peaks) | ✅ | `analysis.py`: Parabolic interpolation peak detection. |
| **EpR Source Curve** (Gain/Slope/Depth) | ✅ | `epr.py`: Eq. 9 fit from Harmonic Spectral Shape (HSS). |
| **EpR Resonances** (Source + Vocal Tract) | ✅ | `epr.py`: Klatt 2nd-order filters (Eq. 3). Max-of-neighbors optimization. |
| **Differential Spectral Shape (DSS)** | ✅ | `epr.py`: 75Hz step envelope (Paper uses 30Hz). |
| **EpR Phase Model** (Resonance $\pi$-shift) | ✅ | `synth.py`: `_phase_model` adds linear phase across bandwidths. |
| **Voiced Harmonic Excitation** | ✅ | `synth.py`: Pulse-phase locked comb (Delta-train equivalent) + Glottal Template phase. |
| **Voiced Residual Excitation** | 🟡 | `vr.py`/`synth.py`: Modeled from sustain, flattened, transposed (rho), filtered by Env+Diff. Blends to noise floor at high rho to avoid aliasing. |
| **Unvoiced Excitation** | 🟡 | `synth.py`: Band-envelope noise. (Paper uses original recording tilt/gain). |
| **Steady States & Diphones** | ✅ | `core.py`/`unit.py`: DB storage with markers (START/P1/P2/TRANS/END). |

### 2. Spectral Transformations (SPP)
*References: SMAC-03 §5*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **SPP Analysis** (Peak Tracking/Phase) | ✅ | added yay |
| **Transposition** (Region Shift) | ✅ | Harmonics are shifted by f * ratio (SMAC-03 §5.1). |
| **Transposition Phase Correction** | ✅ | The accumulated phase increment Δφ = 2π · i · pitch · (transp − 1) · Δt is applied per harmonic using the stored index k (mapped to i). This preserves vertical phase coherence during transposition. |
| **Equalization** (Timbre Change) | ✅ | present in core engine, no user-setting yet |
| **Time Scaling** | 🟡 | `synth.py`: Sustain looping + hold-last-frame. Paper uses near-lossless frequency-domain time scaling [8]. |

### 3. Concatenation & Continuity
*References: SMAC-03 §6*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Phase Continuity Condition** | 🟡 | `synth.py`: `_join` uses accumulator continuity + $\Delta t_{sync}$ approximation. Paper Eq. 3-5 (exact boundary phase solve) not fully implemented. |
| **$\Delta t_{sync}$ Alignment** | ✅ | `synth.py`: Calculated from fundamental phase difference to minimize correction. |
| **Correction Spreading** (Fig. 6) | ⚪ | **Missing**: Paper spreads phase correction over $K$ frames. We use a spectral warp ramp instead. |
| **Spectral Shape Concatenation** (Fig. 7) | 🟡 | `synth.py`: `_join` implements EpR anchor mapping + SSIntp differential envelope morphing (parametric domain). |
| **Unvoiced/Voiced Joints** | ✅ | `synth.py`: Gain crossfade (Xfade) for unvoiced boundaries. |
| **Predictive Amplitude Shaping** (PAS) | ⚪ | **Missing**: Clynes' rule for natural amplitude contours [ICMC-01 §5.1]. |
| **Pitch Contour Model** | 🟡 | `plan.py`: Vowel-onset alignment implemented. Smooth transition model missing. |
| **Expressiveness Rules** (Friberg/Sundberg) | ⚪ | **Missing**: Rule-based deviation system. |

### 4. MicroScore Parameters (Note Level)
*References: ICMC-01 §5 (Table), VOCALOID Diagram*

| Parameter | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Pitch** (MIDI) | ✅ | `plan.py`/`roll_gui.py`: Input via piano roll. |
| **Duration** | ✅ | `plan.py`: Note length in ms. |
| **Grapheme to phoneme conversion** | ⚪ | **Missing**: currently direct phoneme input only. |
| **Syllabic Adjustment** | ⚪ | **Missing**: Automatic syllable-to-note assignment. |
| **Phonemes** (Lyrics) | ✅ | `roll_gui.py`: Direct phoneme entry per note. |
| **Phoneme Timing** | ✅ | `plan.py`/`roll_gui.py`: Per-phoneme overrides (P1/P2/Onsets), anticipation, alignment. |
| **Volume** | ✅ | Volume knob automation. |
| **Gender / Formant Shifter** | ✅ | Works like the global parameter. |
| **Pitch** | ✅ | F0 rendering following singer's modeled pitch, the drift through transitions (the engine's inherent portamento, since rows render the recorded f0 × ratio rather than a snapped MIDI pitch), flat-ish sustain loops, and gaps where frames are unvoiced. Moving the PITCH fader slides the whole curve in fractional-row precision, and because segments are built from self._rows, any later engine-side pitch modeling (explicit portamento curves, release tails, vibrato) automatically appears here the moment it affects the rendered frames. Unit arrays are cached in DB._load, so redrawing stays cheap (~48 samples/row). |
| **Voicing** | ✅ | Works like the global parameter. |
| **Voicing** | ✅ | Works like the global parameter. |
| **Vibrato** (Type/Depth/Rate) | ✅ | Vibrato tool added. No modeling yet. |
| **Breathiness** | ⚪ | Missing. |
| **Brightness** | ⚪ | Missing. |
| **Tension** | ⚪ | Missing. |
| **Attack Type/Duration** | ⚪ | **Missing**: No specific attack templates (Sharp/Soft/High). |
| **Body Type/Duration** | ⚪ | **Missing**: No specific body templates. |
| **Release Type/Duration** | ⚪ | **Missing**: No specific release templates. |
| **Transition Type** (Legato/Staccato) | 🟡 | `plan.py`: Implicit legato via overlap/anticipation. No explicit Staccato/Portamento controls. |
| **Opening of Vowels** | ⚪ | **Missing**: Formant scaling control. |

### 5. Global Controls & Expression
*References: ICMC-01 §5.1, VOCALOID Diagram*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Vocal Style** | ⚪ | **Missing**: Manifest has stub `styles=base`, but no style switching logic. |
| **Language Picker (G2P changer)** | ⚪ | **Missing**: currently direct phoneme input. |
| **Volume** | ✅ | its a volume knob. |
| **Gender Shift / Note-locked Formant Shifter** | ✅ | Formants drift proportionally to how far the note is from the recorded pitch. |
| **Gender / Formant Shifter** | ✅ | GENDER multiplies the VT resonance frequencies and stretches the DSS axis by gf (0.71×–1.41×). Formants physically move in the model, so at ratio == 1 turning the slider down darkens/masculinizes and turning it up brightens/femininizes — symmetric, no note dependence. The source curve and source resonance (glottal tilt, low‑frequency content) stay untouched, so it reads as tract size, not as a filter sweep. |
| **Pitch** | ✅ | Slider 50 = concert pitch (A4 = 440 Hz); 0 = −100 cents (one semitone down); 100 = +100 cents (one semitone up). Because it's applied through the per‑row transposition ratio, the SPP renderer's eq.‑2 phase accumulation and the formant anchoring (vt_scale = gender·ratio^gshift) all react consistently — push it up a semitone and you get the slight natural formant drift you tuned G‑SHIFT for, push G‑SHIFT to 0 and the timbre stays locked while the melody moves. |
| **Voicing** | ✅ | 0 will unvoice the synthesized string completely, bringing it gradually up. |
| **Breathiness** | 🟡 | Implemented naturally via the voiced residual models, but doesn't produce a noticeable effect. |
| **Brightness / High-EQ** | ✅ | SPP+artificial high shelf EQ. |
| **Tension / Mid-EQ** | ✅ | SPP+artificial mid shelf EQ.. |
| **Voice Conversion** | ⚪ | **Missing**: No cross-synthesis/morphing. |
| **Auto Pitch Model Skill** | ⚪ | **Missing**: coming veeeeery later on. expect simple hmm based autopitch ijbol. |

### 6. Database & Tools
*References: ICMC-01 §6, Dev Tools*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Diphone Library** | ✅ | `core.py`: Batchlab/OTO import, segmentation, modeling. |
| **Timbre DB Interpolation** | 🟡 | `synth.py`: Pitch-group floor rule (nearest neighbor). No interpolation between pitches/dynamics. |
| **Vibrato Templates** | ⚪ | **Missing**: Attack/Body/Release segmentation storage. |
| **Note Attack/Release Templates** | ⚪ | **Missing**: Storage and playback of boundary templates. |
| **Language Config** | ✅ | `langcfg.py`: Phoneme categories (Plosive/Nasal/etc.) for analysis parameters. |
| **EpR Workbench** | ✅ | `epr_gui.py`: Visual modeling, category-driven analysis, authentic pitch. |
| **Unit Editor** | ✅ | `gui.py`: Waveform preview, marker dragging, re-modeling. |
| **Label Writer** | ✅ | `gui.py`: Wav+Lab -> Model pipeline. |
| **OTO -> Batchlab** | ✅ | `oto_gui.py`: Converter with alias splitting (Romaji/Kana/ARPAbet). |

