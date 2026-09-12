

# EpR Synthesizer

The EpR Synthesizer is a concatenative singing voice synthesis engine featuring a modern, dark-themed piano roll editor. It uses an Envelope-based Pitch-synchronous Resynthesis (EpR) core with Spectral Peak Processing (SPP) for high-fidelity rendering, and integrates the OpenUtau G2P standard for automatic lyric-to-phoneme conversion.

## Features

### Synthesis Engine
*   **EpR Core:** High-quality concatenative synthesis with natural formant transitions. Like V*CALOID1.
*   **SPP Fallback:** Spectral Peak Processing for cleaner high-frequency rendering and phase continuity.
*   **Advanced Modulation:** Position-aware MODULATION parameter that pins pre-onset consonants to the previous note's pitch, eliminating early pitch hikes.
*   **Fast Passage Handling:** Automatic time-compression of diphones with SPP phase rebasing to keep timing accurate during fast notes.
*   **Flexible Voicing:** Full control over breathiness, tension, brightness, and voicing, with modeled voiced residuals.

### Piano Roll Editor (`roll_ui.py`)
*   **Modern UI:** Flat, dark/orange interface with thin scroll rails and custom canvas faders.
*   **Curve Editing:** Drawable lanes for Pitch, Volume, Gender, Voicing, Breathiness, Brightness, Tension, and Formants (F1/F2/F3).
*   **Vibrato:** Fully draggable vibrato envelopes with ease-in/out, frequency, and amplitude controls.
*   **Portamento:** Per-note pitch transition faders (Offset, Duration, Depth) for precise glide shaping.
*   **Articulation Strip:** Visual timeline of phonemes and diphones. Drag handles to adjust chain heads, pre-onsets, releases, and internal phoneme timings.
*   **Settings Pane:** Persisted engine defaults (excitation template, SPP/EpR toggle, global parameters) saved locally, independent of project files.

### Lyrics & G2P Workflow
*   **Inline Editors:** Double-click the note body to enter lyrics; double-click the top phoneme label to edit raw phonemes.
*   **Phoneme Lock:** Manually editing phonemes engages a "lock" that prevents lyric commits from overwriting your manual work.
*   **OpenUtau G2P Integration:** Supports unzipped G2P packs (Dictionary + ONNX model). Automatically selects the correct pack based on the voice's language code (e.g., `en-arpa` maps to `g2p-en-arpa`).
*   **Symbol Mapping:** `convert.txt` support to map G2P symbols (like ARPAbet or X-SAMPA) directly to the engine's native phoneme set.

---

## Prerequisites

*   **Python:** 3.10 or higher (3.14 recommended).
*   **Dependencies:** `numpy`, `scipy`, `onnxruntime` (optional, for G2P model inference).
*   **GUI:** Tkinter (usually included with standard Python installations).

---

## Installation

### macOS
1.  Install Python via Homebrew (recommended for M-series chips) or python.org:
    ```bash
    brew install python@3.14
    ```
2.  Clone the repository and install dependencies:
    ```bash
    git clone <your-repo-url>
    cd AURORA
    python3 -m pip install numpy scipy onnxruntime
    ```
3.  Run the editor:
    ```bash
    python3 -m svs.roll_ui
    ```

### Windows
1.  Download and install Python 3.10+ from [python.org](https://www.python.org/). Ensure "Add Python to PATH" is checked.
2.  Open Command Prompt or PowerShell, clone the repository, and install dependencies:
    ```powershell
    git clone <your-repo-url>
    cd AURORA
    pip install numpy scipy onnxruntime
    ```
3.  Run the editor:
    ```powershell
    python -m svs.roll_ui
    ```

---

## Usage Guide

### 1. Loading a Voice
*   Click the **VOICE** button in the top transport bar.
*   Select a voice folder (must contain `manifest.ini` and `lang.ini`) or click `<open...>` to browse.
*   The editor will automatically detect the language code (e.g., `ja`, `en-arpa`) and load the corresponding G2P pack if available.

### 2. Drawing Notes & Curves
*   **Draw Mode:** Select `DRAW` in the top right. Click on the grid to create notes.
*   **Select/Move:** Select `SELECT`. Click and drag notes to move or resize them.
*   **Curves:** Click `CURVES` to open the curve lane. Select a parameter tab (e.g., `PITCH`) and use `DRAW` to paint strokes. Right-click the lane to add vibratos.
*   **Playback:** Press `Space` to play/pause. (Note: Space is disabled while typing in text boxes).

### 3. Lyrics and Phonemes
*   **Entering Lyrics:** Double-click the **body** of a note. A text box appears. Type a word (e.g., `loula`) and press `Enter`. The engine will run it through the G2P pack and place the phonemes on the note.
*   **Editing Phonemes:** Double-click the **orange phoneme text** above the note. Edit the raw symbols (e.g., `l ow l ah`) and press `Enter`. This automatically engages the **Lock**.
*   **The Lock:** When locked, typing new lyrics will update the displayed lyric text but will *not* overwrite the manually edited phonemes. Click the `lock` chip in the right-click note menu to toggle it.
*   **Articulation Strip:** The bottom timeline shows phoneme blocks. Drag the white vertical bars to adjust internal phoneme timings or the orange blocks to adjust diphone splits.

### 4. Settings & Parameters
*   **Global Parameters:** Click `PARAMS` to open the fader window (Volume, Gender, Pitch, etc.). Double-click a fader to reset it.
*   **Settings Pane:** Click `SETTINGS` in the top right. Here you can toggle between `delta`/`glottal` excitation, `use spp`/`use epr comb`, and set default parameter values. These settings are saved to `roll_settings.json` and persist across sessions.
*   **Project Overrides:** Parameters saved in the `.json` sequence file will override the Settings pane defaults when loaded.

---

## File Structure

### Voices
Voices are organized in folders containing:
*   `manifest.ini`: Metadata (singer name, language code, version).
*   `lang.ini`: Phoneme categories (vowels, consonants, steady states).
*   `base/`: Pitch groups containing `index.json`, diphone `.npz` files, and steady state loops.

### G2P Packs
Place unzipped G2P folders in `svs/g2p/`. Each folder must contain:
*   `dict.txt`: Sphinx format dictionary (`WORD PH1 PH2 ...`).
*   `phones.txt`: Phoneme symbols in model order.
*   `*.onnx`: The RNN-T model file (optional; dictionary-only works without it).
*   `convert.txt` (Optional): Maps G2P symbols to engine phonemes (e.g., `AO ao`).

---

## Troubleshooting

*   **"onnxruntime not installed":** The G2P system will still work using the dictionary. To enable model inference, run `pip install onnxruntime`.
*   **Spacebar starts playback while typing:** The editor automatically detects focus on `Entry` or `Text` widgets and disables the spacebar shortcut. If it persists, ensure you are using the latest `roll_ui.py`.
*   **Lyrics rejected:** Check the terminal output. It will print exactly which phonemes were generated and which are missing from the voice's `lang.ini`. Ensure your `convert.txt` or G2P pack matches the engine's phoneme set.
*   **Pitch jumps at consonants:** Ensure `MODULATION` is set appropriately. The engine uses position-aware flattening to keep pre-onset consonants on the previous note's pitch.
