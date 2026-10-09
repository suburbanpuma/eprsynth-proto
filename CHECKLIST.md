# CHECKLIST.md

**Legend:**

- ✅ **Implemented**: Fully functional in the current codebase.
- 🟡 **In Progress / Approximate**: Implemented with a simplified or alternative method (e.g., parametric instead of SPP, noise-floor instead of inverse-filtered residual).
- ⚪ **Missing / Removed**: Not yet implemented, or intentionally removed to streamline the tool.

### 1. Core Synthesis Engine (EpR & Excitation)

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

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **SPP Analysis** (Peak Tracking/Phase) | ✅ | Added. |
| **Transposition** (Region Shift) | ✅ | Harmonics are shifted by f * ratio (SMAC-03 §5.1). |
| **Transposition Phase Correction** | ✅ | The accumulated phase increment Δφ = 2π · i · pitch · (transp − 1) · Δt is applied per harmonic using the stored index k (mapped to i). This preserves vertical phase coherence during transposition. |
| **Equalization** (Timbre Change) | ✅ | Present in core engine (Brightness/Tension shelves + F1/F2/F3 curves). |
| **Time Scaling** | ✅ | `synth.py`: Sustain looping now uses `_loop_frames` with fig.7 envelope morph and per-harmonic SPP phase continuity at every wrap for seamless held notes. Fast passages use SPP phase rebasing. |

### 3. Concatenation & Continuity

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Phase Continuity Condition** | ✅ | `synth.py`: `_loop_frames` tracks phase per-harmonic in a dict (handling varying peak counts) to ensure seamless wraps. `_join` uses accumulator continuity + Δtsync. |
| **Δtsync Alignment** | ✅ | `synth.py`: Calculated from fundamental phase difference to minimize correction. |
| **Correction Spreading** (Fig. 6) | 🟡 | `synth.py`: We use a spectral warp ramp instead of explicit phase spreading over K frames. |
| **Spectral Shape Concatenation** (Fig. 7) | ✅ | `synth.py`: `_join` implements EpR anchor mapping + SSIntp differential envelope morphing. `_loop_frames` also uses this to morph the last K frames of a sustain pass toward the pass head, eliminating loop clicks. |
| **Unvoiced/Voiced Joints** | ✅ | `synth.py`: Gain crossfade (Xfade) for unvoiced boundaries. |
| **Predictive Amplitude Shaping** (PAS) | ⚪ | **Missing**: Clynes' rule for natural amplitude contours [ICMC-01 §5.1]. |
| **Pitch Contour Model** | ✅ | `plan.py`/`synth.py`: Vowel-onset alignment + shaped portamento transitions (`pt_trans`) + MODULATION parameter. |
| **Expressiveness Rules** (Friberg/Sundberg) | ⚪ | **Missing**: Rule-based deviation system. |

### 4. MicroScore Parameters (Note Level)

| Parameter | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Pitch** (MIDI) | ✅ | `plan.py`/`roll_ui.py`: Input via piano roll. |
| **Duration** | ✅ | `plan.py`: Note length in ms. |
| **Lyrics** | ✅ | `roll_ui.py`: Inline lyric editing with G2P conversion. |
| **Grapheme to phoneme conversion** | ✅ | Uses OpenUtau compatible G2P models. Auto-selects pack based on voice `manifest.ini` language code. |
| **Syllabic Adjustment** | ⚪ | **Missing**: Currently, there's no syllabic phoneme adjustment. |
| **Phonemes** | ✅ | `roll_ui.py`: Direct phoneme entry per note. Added dot-prefix (e.g., `.sil`) for direct input bypassing G2P. |
| **Vocal Style** | ⚪ | **Missing**: Manifest supports styles listings but there's no way to switch them per-note in the engine yet. |
| **Phoneme Timing** | ✅ | `plan.py`/`roll_ui.py`: Per-phoneme overrides (P1/P2/Onsets), anticipation, alignment. |
| **Volume** | ✅ | Volume curve automation. |
| **Gender / Formant Shifter** | ✅ | Works like the global parameter. |
| **Pitch** | ✅ | F0 rendering following singer's modeled pitch. Pencil curves override base F0. |
| **Voicing** | ✅ | Fades harmonic part, brings in whisper component. |
| **Vibrato** (Type/Depth/Rate) | ✅ | `roll_ui.py`: Draggable vibrato envelopes with ease-in/out, frequency, and amplitude controls. |
| **Breathiness** | ✅ | Synthesized aspiration noise + voiced residual blending. |
| **Brightness** | ✅ | High-shelf EQ applied to SPP harmonics. |
| **Tension** | ✅ | Mid-bell EQ applied to SPP harmonics. |
| **Portamento** | ✅ | `synth.py`: Shaped portamento transitions (`pt_trans`) replace f0 inside their window with a smoothstep S-curve. `MODULATION` parameter flattens steady regions to lock to exact note pitch. |
| **Vowel Formant Shifter (IPA)** | 🟡 | `roll_ui.py`/`vowel_preset.py`: Right-click a vowel in the timing strip to open an IPA trapezoid chart. Retargeting bakes absolute F1/F2/F3 Hz curves over the full vowel extent (c-v half -> sustain -> v-c half). Currently a WIP.|
| **F1/F2/F3 Curve Lanes** | ✅ | `roll_ui.py`: Drawable lanes for absolute formant frequencies, layered with the vowel shifter's baked curves. |
| **Attack/Body/Release Effects** | ⚪ | **Missing**: No template implementation yet. |

### 5. Global Controls & Expression

| Feature | Status | Implementation Notes |
| :-- | :-: | :-- |
| **Vocal Style** | ⚪ | **Missing**: Manifest has stub `styles=base`, but no style switching logic. |
| **Language Picker (G2P changer)** | ✅ | Auto-detects language from `manifest.ini` and loads the corresponding `g2p-<lang>` pack and `vowel_map`. |
| **Volume** | ✅ | Global volume scalar + curve. |
| **Gender Shift / Note-locked Formant Shifter** | ✅ | Formants drift proportionally to how far the note is from the recorded pitch (G-SHIFT). |
| **Gender / Formant Shifter** | ✅ | GENDER multiplies the VT resonance frequencies and stretches the DSS axis. |
| **Pitch** | ✅ | Global pitch slider (+-100 cents). Applied through the per-row transposition ratio. |
| **Voicing** | ✅ | Global scalar + curve. |
| **Breathiness** | ✅ | Implemented naturally via the voiced residual models + synthesized air. |
| **Brightness / High-EQ** | ✅ | Global scalar + curve. |
| **Tension / Mid-EQ** | ✅ | Global scalar + curve. |
| **Immediate Auto-Rendering** | ✅ | `roll_ui.py`: Background render triggers immediately on gesture end, lyric commit, or sequence load. |

### 6. Database & Tools

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
