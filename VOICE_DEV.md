# Creating a Voice Database for the EpR Synthesizer

This guide explains how to create a voice database using the SVS Developer Tool (`gui.py`).

## Overview

A voice database consists of:
- **Pitch groups** (e.g., C2, A3, G4) - different pitch ranges
- **Styles** (e.g., base, soft, power) - different vocal characteristics (NOT IMPLEMENTED YET)
- **Units** - diphones (transitions between phonemes) and sustains (steady-state vowels)
- **Labels** - timing markers for phoneme boundaries

## Prerequisites

- Recorded voice samples (WAV files, 44.1kHz or 48kHz recommended)
- Label files (.lab) marking phoneme boundaries, OR use the integrated label writer

## Step-by-Step Guide

### 1. Create a New Database

1. Open the **Database** tab
2. Fill in the fields:
   - **Name**: Voice name (e.g., "Aurora")
   - **Developer**: Your name/studio
   - **Version**: e.g., "100"
   - **Language**: Select from dropdown (ja, en-arpa, etc.)
   - **Pitch groups**: Comma-separated list (e.g., "C2, A3, G4")
     - Choose pitches that cover the singer's comfortable range
     - You should be able to do as many pitches as you want
   - **Styles**: Comma-separated (e.g., "base, soft, power")
     - "base" is required and created automatically
    
3. Click **Create...** and select an empty folder inside the voices subfolder

### 2. Import Recordings

1. Go to the **Import** tab
2. Select the pitch **Group** from dropdown
3. Click **wav...** to select your recording
4. Click **labels...** to select the corresponding .lab file
5. Click **Import**

Compatible lab file format example (represents PHONEME1 START P1 TRANS END for sustains and PHONEME1 PHONEME2 START P1 P2 TRANS END for articulations):
```
o 7166.8 7277.6 7729.3 7831.5
e 1568.0 1721.4 2121.9 2215.7
i 2386.1 2496.9 3119.0 3187.1
a 5726.6 5931.2 6255.0 6357.2
sil d 9.9 47.5 107.9 200.0 243.6
d o 104.0 240.6 424.8 778.2 911.9
o rr 1039.6 1099.0 1226.7 1268.3 1304.0
rr e 1265.3 1309.9 1419.8 1728.7 1808.9
```

### 3. Edit Units

After importing, refine the timing markers if needed:

1. Go to the **Units** tab
2. Select a **group** from dropdown
3. Click on a unit in the tree:
   - **Diphones**: transitions like "k a", "a t"
   - **Sustains**: steady vowels like "~a"
4. The waveform preview shows the **modeled** output
5. Drag the colored markers:
   - **P1** (blue): Start of consonant
   - **P2** (green): End of consonant / start of vowel
   - **TRANS** (orange): Transition point
   - **END** (red): End of unit
6. Click **Apply timing** to save changes
7. Press **Space** to audition the unit

**Re-model from source:**
If you need to rebuild a unit from different source material:
1. Select the unit
2. Click **Re-model from wav+lab...**
3. Select new WAV and label files
4. The tool will rebuild the unit preserving your marker positions

### 4. Write Labels Manually

If you don't have label files, use the **Label writer**:

1. Go to the **Label writer** tab
2. Click **wav...** to load a recording
3. Select the pitch **group**
4. Set the view range (ms) and click **Zoom**
5. Click **+ articulation** or **+ sustain** to add labels
6. Drag markers on the waveform to adjust timing:
   - **START**: Beginning of segment
   - **P1**: Consonant onset
   - **P2**: Consonant offset / vowel onset
   - **TRANS**: Transition point
   - **END**: End of segment
7. Edit phoneme names in the listbox
8. Click **Save lab** to export .lab file
9. Click **Model into DB** to directly import into the database

### 5. Verify and Test

1. In the **Units** tab, check the **missing steady** banner
   - All steady-capable phonemes should have sustains
2. Press **Space** to audition units
3. Switch to the piano roll editor (`roll_ui.py`) to test singing

## Database Structure

The created database folder looks like:
```
my_voice/
├── manifest.ini           # Metadata (name, author, styles, groups)
├── base/                  # Default style
│   ├── C3/
│   │   ├── index.json     # Unit inventory
│   │   ├── k a.npz        # Diphone data
│   │   └── ~a.npz         # Sustain data
│   ├── G4/
│   │   └── ...
├── soft/                  # Additional styles
│   └── ...
└── lang.ini               # Phoneme definitions (from template)
```

## Tips

### Recording Guidelines
- Record in a quiet environment
- Use consistent microphone position

### Phoneme Coverage
- Ensure all phonemes in `lang.ini` have:
  - At least one diphone entering and exiting (sil X, X sil) for nasals and vowels
  - A sustain if marked as steady-capable (vowels, nasals by default)
- Check the "missing steady" warning in Units tab
- Note that you don't need to cover all diphones, as the engine will compensate.

### Quality Control
- Listen to every unit with Space
- Adjust markers if transitions sound glitchy
- Re-model units with poor source recordings
- Use the label writer to create precise timings

## Troubleshooting

**"unmapped alias"**: Add the alias to `dict.txt` or use phonemes directly in oto.ini

**"missing steady"**: Record and import sustain samples for vowels/nasals

**Glitchy transitions**: Adjust P2/TRANS markers in Units tab

**Pitch jumps**: Ensure pitch groups overlap and have sufficient coverage

## Next Steps

Once your database is complete:
1. Open the piano roll editor (`python -m svs.roll_ui`)
2. Load your voice via the **VOICE** button
3. Start composing!
