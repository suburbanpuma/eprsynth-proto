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

### 4. MicroScore Parameters (Note Level)
*References: ICMC-01 §5 (Table), VOCALOID Diagram*

| Parameter | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Pitch** (MIDI) | ✅ | `plan.py`/`roll_gui.py`: Input via piano roll. |
| **Duration** | ✅ | `plan.py`: Note length in ms. |
| **Phonemes** (Lyrics) | ✅ | `roll_gui.py`: Direct phoneme entry per note. |
| **Phoneme Timing** | ✅ | `plan.py`/`roll_gui.py`: Per-phoneme overrides (P1/P2/Onsets), anticipation, alignment. |
| **Loudness / Dynamics** | ⚪ | **Missing**: No volume curve or dynamic envelope control yet. |
| **Pitch Envelope** | ⚪ | **Missing**: No pitch bend/vibrato curve drawing or playback. |
| **Attack Type/Duration** | ⚪ | **Missing**: No specific attack templates (Sharp/Soft/High). |
| **Release Type/Duration** | ⚪ | **Missing**: No specific release templates. |
| **Transition Type** (Legato/Staccato) | 🟡 | `plan.py`: Implicit legato via overlap/anticipation. No explicit Staccato/Portamento controls. |
| **Vibrato** (Type/Depth/Rate) | ⚪ | **Missing**: No vibrato synthesis or templates. |
| **Opening of Vowels** | ⚪ | **Missing**: Formant scaling control. |
| **Breathiness / Air** | 🟡 | `config.py`: Global `vr_gain`. No per-note curve. |
| **Hoarseness** | ⚪ | **Missing**: No specific control (partially covered by residual). |
| **Whisper** | ⚪ | **Missing**: No unvoiced-mix control. |

### 5. Global Controls & Expression
*References: ICMC-01 §5.1, VOCALOID Diagram*

| Feature | Status | Implementation Notes |
| :--- | :---: | :--- |
| **Brightness / High-EQ** | ⚪ | **Missing**: Requires Equalization (SPP). |
| **Tension / Mid-EQ** | ⚪ | **Missing**: Requires Equalization (SPP). |
| **Gender / Formant Shifter** | ⚪ | **Missing**: Requires EpR anchor stretching (machinery exists in `_join` but not exposed as control). |
| **Voice Conversion** | ⚪ | **Missing**: No cross-synthesis/morphing. |
| **Auto Pitch Model Skill** | ⚪ | **Missing**: No automatic pitch correction/smoothing rules. |
| **Vocal Style** | ⚪ | **Missing**: Manifest has stub `styles=base`, but no style switching logic. |
| **Grapheme-to-Phoneme (G2P)** | ⚪ | **Missing**: Lyrics input branch (VOCALOID diagram left side). |
| **Syllabic Adjustment** | ⚪ | **Missing**: Automatic syllable-to-note assignment. |
| **Predictive Amplitude Shaping** (PAS) | ⚪ | **Missing**: Clynes' rule for natural amplitude contours [ICMC-01 §5.1]. |
| **Pitch Contour Model** | 🟡 | `plan.py`: Vowel-onset alignment implemented. Smooth transition model missing. |
| **Expressiveness Rules** (Friberg/Sundberg) | ⚪ | **Missing**: Rule-based deviation system. |

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

