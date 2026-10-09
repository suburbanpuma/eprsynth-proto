# CHECKLIST.md

**Legend:**

- ✅ **Implemented**: Fully functional in the current codebase.
- 🟡 **In Progress / Approximate**: Implemented with a simplified or alternative method (e.g., parametric instead of SPP, noise-floor instead of inverse-filtered residual).
- ⚪ **Missing / Removed**: Not yet implemented, or intentionally removed to streamline the tool.

### 1. Core Synthesis Engine (EpR & Excitation)

_References: ICMC-01 §3, SMAC-03 §3_

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **SMS Analysis Front-end** (STFT + Peaks) | ✅ | `analysis.py`: Parabolic interpolation peak detection. |
| **EpR Source Curve** (Gain/Slope/Depth) | ✅ | `epr.py`: Eq. 9 fit from Harmonic Spectral Shape (HSS). |
| **EpR Resonances** (Source + Vocal Tract) | ✅ | `epr.py`: Klatt 2nd-order filters (Eq. 3). Max-of-neighbors optimization. |
| **Differential Spectral Shape (DSS)** | ✅ | `epr.py`: 75Hz step envelope (Paper uses 30Hz). |
| **EpR Phase Model** (Resonance π-shift) | ✅ | `synth.py`: `_phase_model` adds linear phase across bandwidths. |
| **Voiced Harmonic Excitation** | ✅ | `synth.py`: Pulse-phase locked comb (Delta-train equivalent) + Glottal Template phase. |
| **Voiced Residual Excitation** | 🟡 | `vr.py`/`synth.py`: Modeled from sustain, flattened, transposed (rho), filtered by Env+Diff. Blends to noise floor at high rho to avoid aliasing. |
| **Unvoiced Excitation** | 🟡 | `synth.py`: Band-envelope noise. (Paper uses original recording tilt/gain). |
| **Steady States & Diphones** | ✅ | `core.py`/`unit.py`: DB storage with markers (START/P1/P2/TRANS/END). |

### 2. Spectral Transformations (SPP)

_References: SMAC-03 §5_

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **SPP Analysis** (Peak Tracking/Phase) | ✅ | Implemented via peak tracking and instantaneous phase extraction during SMS analysis. |
| **Transposition** (Region Shift) | ✅ | Harmonics are shifted by `f * ratio` (SMAC-03 §5.1). |
| **Transposition Phase Correction** | ✅ | `spp_acc` dictionary accumulates phase increment `Δφ = 2π · k · pitch · (transp − 1) · Δt` per harmonic. Re-derives harmonic index `k` from peak frequencies against sanitized recorded `f0r` to prevent octave jumps at consonant onsets. |
| **Equalization** (Timbre Change) | ✅ | Implemented as high-shelf (Brightness) and mid-bell (Tension) EQ curves applied directly to SPP harmonic amplitudes in dB, plus absolute F1/F2/F3 frequency overrides via spectral warping. |
| **Time Scaling** | ✅ | `synth.py`: Sustain loops now use `_loop_frames` with a fig.7 anchor/envelope morph over the last K frames toward the loop head, combined with per-harmonic SPP phase continuity via a harmonic-keyed dictionary. This eliminates loop clicks and phase discontinuities. Fast passages use time-compression with SPP phase rebasing. |

### 3. Concatenation & Continuity

_References: SMAC-03 §6_

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Phase Continuity Condition** | ✅ | `synth.py`: `_join` uses accumulator continuity + Δtsync. For loops, `_loop_frames` tracks phase per-harmonic in a dictionary to ensure seamless wraps even when peak counts vary frame-to-frame. |
| **Δtsync Alignment** | ✅ | `synth.py`: Calculated from fundamental phase difference to minimize correction. |
| **Correction Spreading** (Fig. 6) | 🟡 | `synth.py`: We use a spectral warp ramp (fig.7) instead of explicit phase spreading over K frames. |
| **Spectral Shape Concatenation** (Fig. 7) | ✅ | `synth.py`: `_join` implements EpR anchor mapping + SSIntp differential envelope morphing. `_loop_frames` also uses this to morph the last K frames of a sustain pass toward the pass head, eliminating loop timbre steps. |
| **Unvoiced/Voiced Joints** | ✅ | `synth.py`: Gain crossfade (Xfade) for unvoiced boundaries. |
| **Predictive Amplitude Shaping** (PAS) | ⚪ | **Missing**: Clynes' rule for natural amplitude contours [ICMC-01 §5.1]. |
| **Pitch Contour Model** | ✅ | `plan.py`/`synth.py`: Vowel-onset alignment implemented. Smooth transition model implemented via `pt_trans` (shaped smoothstep S-curves replacing f0 inside transition windows) and the `MODULATION` parameter which flattens steady regions to lock to exact note pitch while allowing recorded glides at boundaries. |
| **Expressiveness Rules** (Friberg/Sundberg) | ⚪ | **Missing**: Rule-based deviation system. |

### 4. MicroScore Parameters (Note Level)

_References: ICMC-01 §5 (Table), VOCALOID Diagram_

| Parameter | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Pitch** (MIDI) | ✅ | `plan.py`/`roll_ui.py`: Input via piano roll. |
| **Duration** | ✅ | `plan.py`: Note length in ms. |
| **Lyrics** | ✅ | `roll_ui.py`: Inline lyric editing in the piano roll with automatic Grapheme-to-Phoneme (G2P) conversion based on the voicebank's language. |
| **Grapheme to phoneme conversion** | ✅ | Uses OpenUtau-compatible G2P models. Auto-selects the correct language pack based on the voicebank's `manifest.ini`. |
| **Syllabic Adjustment** | ⚪ | **Missing**: Currently, there's no syllabic phoneme adjustment. |
| **Phonemes** | ✅ | `roll_ui.py`: Direct phoneme entry per note. Supports dot-prefix (e.g., `.sil`) for direct phoneme input bypassing G2P. |
| **Vocal Style** | ⚪ | **Missing**: Manifest supports styles listings but there's no way to add them into the db or switch them in engine. |
| **Phoneme Timing** | ✅ | `plan.py`/`roll_ui.py`: Per-phoneme overrides (P1/P2/Onsets), anticipation, alignment. |
| **Volume** | ✅ | Volume curve automation. |
| **Gender / Formant Shifter** | ✅ | Works like the global parameter. |
| **Pitch** | ✅ | F0 rendering following singer's modeled pitch. Pencil curves override base F0. Portamento transitions layer underneath. |
| **Voicing** | ✅ | Fades harmonic part, brings in whisper component. |
| **Vibrato** (Type/Depth/Rate) | ✅ | `roll_ui.py`: Draggable vibrato envelopes in the piano roll with ease-in/out, frequency, and amplitude controls. Multiplied onto f0 during synthesis. |
| **Breathiness** | ✅ | Synthesized aspiration noise + voiced residual blending. |
| **Brightness** | ✅ | High-shelf EQ applied to SPP harmonics. |
| **Tension** | ✅ | Mid-bell EQ applied to SPP harmonics. |
| **Portamento** | ✅ | `synth.py`: Shaped portamento transitions (`pt_trans`) replace f0 inside their window with a smoothstep S-curve. `MODULATION` parameter flattens steady regions to lock to exact note pitch. |
| **Vowel Formant Shifter (IPA)** | 🟡 | `roll_ui.py`/`vowel_preset.py`: Right-click a vowel in the timing strip to open an IPA trapezoid chart. Retargeting bakes absolute F1/F2/F3 Hz curves over the full vowel extent (c-v half -> sustain -> v-c half). WIP! |
| **F1/F2/F3 Curve Lanes** | ✅ | `roll_ui.py`: Drawable lanes for absolute formant frequencies, layered with the vowel shifter's baked curves. |
| **Attack/Body/Release Effects** | ⚪ | **Missing**: No template implementation yet. |

### 5. Global Controls & Expression

_References: ICMC-01 §5.1, VOCALOID Diagram_

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Vocal Style** | ⚪ | **Missing**: Manifest has stub `styles=base`, but no style switching logic. |
| **Language Picker (G2P changer)** | ✅ | Auto-detects language from `manifest.ini` and loads the corresponding G2P pack and `vowel_map`. |
| **Volume** | ✅ | Global volume scalar + curve automation. |
| **Gender Shift / Note-locked Formant Shifter** | ✅ | Formants drift proportionally to how far the note is from the recorded pitch (G-SHIFT). |
| **Gender / Formant Shifter** | ✅ | GENDER multiplies the VT resonance frequencies and stretches the DSS axis. |
| **Pitch** | ✅ | Global pitch slider (+-100 cents). Applied through the per-row transposition ratio. |
| **Voicing** | ✅ | Global scalar + curve. |
| **Breathiness** | ✅ | Implemented naturally via the voiced residual models + synthesized air. |
| **Brightness / High-EQ** | ✅ | Global scalar + curve. |
| **Tension / Mid-EQ** | ✅ | Global scalar + curve. |
| **Immediate Auto-Rendering** | ✅ | `roll_ui.py`: Background render triggers immediately on gesture end, lyric commit, or sequence load in the piano roll. |

### 6. Database & Tools

_References: ICMC-01 §6, Dev Tools_

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Diphone Library** | ✅ | `core.py`: Wav+Lab import, segmentation, modeling. |
| **Timbre DB Interpolation** | 🟡 | `synth.py`: Pitch-group floor rule (nearest neighbor). No interpolation between pitches/dynamics. |
| **Vibrato Templates** | ⚪ | **Missing**: Attack/Body/Release segmentation storage. |
| **Note Attack/Release Templates** | ⚪ | **Missing**: Storage and playback of boundary templates. |
| **Language Config** | ✅ | `langcfg.py`: Phoneme categories (Plosive/Nasal/etc.) for analysis parameters. |
| **EpR Workbench** | ✅ | `epr_gui.py`: Visual modeling, category-driven analysis, authentic pitch. |
| **Unit Editor** | ✅ | `gui.py`: Waveform preview, marker dragging, re-modeling. |
| **Label Writer** | ✅ | `gui.py`: Wav+Lab -> Model pipeline. |
| **Simple Timing Mode** | ✅ | `roll_ui.py`: Toggleable view (default ON) showing an optimized vertical-line waveform (1 line per 2 pixels to prevent canvas lag) with white phoneme overlays, grabbable bars, and shadow styling for `sil`/`gs`/`cl` notes. |
