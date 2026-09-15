# Creating a New Language for the EpR Synthesizer

This guide explains how to add support for a new language to the EpR Synthesizer, including phoneme definitions, G2P (grapheme-to-phoneme) configuration, and voice database setup.

## Overview

Adding a new language involves:
1. **Language Configuration** (`lang.ini`) - defining phonemes and their properties
2. **G2P Pack** - mapping text/aliases to phonemes (dictionary + optional ML model)
3. **Voice Database** - recording and labeling phonemes in the target language

---

## 1. Language Configuration (`lang.ini`)

Create a new file in `svs/lang/` named after your language code (e.g., `fr.ini`, `ko.ini`, `zh.ini`).

### Structure

```ini
[language]
name = 

[types]
vowel       = 
nasal       = 
trill       =
fricative   = 
approximant = 
aspirate    = 
plosive     = 
silence     = 

[voiced]          # exceptions to per-type defaults
yes = 
no  =

[steady]          # exceptions; default steady = vowel + nasal
yes =
no  =
```

### Key Sections

**`name`**: The language name.
Use standard ISO 639-1 or 639-2 codes, for example;

| Code | Language | Example |
|------|----------|---------|
| `ja` | Japanese | `ja, ja-romaji, ja-classic` |
| `en` | English | `en, en-arpabet, en-vccv` |
| `fr` | French | `fr, fr-millefeuille, fr-m2rUg` |
| `de` | German | `de, de-marzipan, de-cvc` |
| `es` | Spanish | `es, es-yya, es-njokis` |
| `ko` | Korean | `ko, ko-coda, ko-cvc` |
| `zh` | Chinese | `zh, zh-pinyin, zh-xsampa` |
| `it` | Italian | `it, it-makku, it-yya` |

You can use **suffixes** for phoneme sets:
- `en-arpa` - ARPAbet phonemes
- `en-xsampa` - X-SAMPA phonemes
- `en-vccv` - VCCV-style phonemes

The engine matches language codes exactly, then falls back to prefix matching (e.g., `en-arpa` voice prefers `g2p-en-arpa` over `g2p-en`), but will fall back on the latter if the exact match is missing.

**`[type]`**: Maps each phoneme to a synthesis type:
- `vowel` - voiced, formant-rich sounds
- `stop` - plosives (k, g, t, d, p, b)
- `fricative` - friction sounds (s, z, h, f, sh)
- `nasal` - nasal sounds (n, m, ng)
- `glide` - semi-vowels (y, w)
- `liquid` - liquids (r, l)
- `silence` - silence/pause markers

Note that affricates are rolled into plosives due to their start as one.

**`voiced`**: Exceptions to phoneme v/uv states. 


**`steady`**: Exceptions to phonemes that can have sustain units (by default it includes vowels, nasals, and pauses).


### Example: Japanese (`ja.ini`)

```ini
# svs/lang/ja.ini
[language]
name = ja

[types]
vowel       = a i u e o N
nasal       = m my n ny
trill       =
fricative   = s sh z f
approximant = w y
aspirate    = h hy
plosive     = k g t d p b ts ch j r ry ky py dy ty gy by
silence     = sil gs cl

[voiced]          # exceptions to per-type defaults
yes = g z b d j
no  =

[steady]          # exceptions; default steady = vowel + nasal
yes =
no  =
```

---

## 2. G2P (Grapheme-to-Phoneme) Configuration

Create a G2P pack folder in `svs/g2p/` (e.g., `g2p-fr`, `g2p-ko`, `g2p-zh`).

### Required Files

#### **`phones.txt`** - Phoneme symbol and type list

```
a	vowel
i	vowel
u	vowel
e	vowel
o	vowel
N	vowel
k	plosive
g	plosive
t	plosive
d	plosive
b	plosive
p	plosive
ts	plosive
ch	plosive
j	plosive
r	plosive
h	aspirate
s	fricative
sh	fricative
z	fricative
f	fricative
w	approximant
y	approximant
m	nasal
n	nasal
ny	nasal
```

#### **`dict.txt`** - Word-to-Phoneme Dictionary

Maps words to phoneme sequences. Format: `ALIAS P1 P2 ...`

```
# Comments start with #
a a
i i
u u
e e
o o
n N
ka k a
ki k i
ku k u
ke k e
ko k o
ga g a
gi g i
gu g u
ge g e
go g o
sa s a
shi sh i
si sh i
su s u
se s e
so s o
```

**Notes:**
- Use spaces to separate phonemes
- Aliases can be single characters (hiragana/kana) or multi-character (romaji)
- For languages with complex orthography (English, French), you may need thousands of entries


#### **Optional: `model.onnx`** - Neural G2P Model

For languages with complex spelling-to-sound rules (English, French), you can use or train an ONNX model using the OpenUtau G2P toolkit:

The model handles OOV (out-of-vocabulary) words that aren't in `dict.txt`.

#### **Optional: `convert.txt`** - Symbol Mapping

If the G2P dictionary or ONNX model uses a different phoneme alphabet than the one you wish to use, you can use a space separated text file to convert them.

```
# G2P symbol -> Engine phoneme
aa	A
ae	{
ah	V
ao	O
aw	aU
ay	aI
ax	@
ch	tS
dh	D
dx	4
eh	E
er	3
```

In this example, the file converts ARPAbet phonemes to X-SAMPA.


---

## 3. Voice Database Creation

Once the language and G2P are configured, create a voice database. Use the VOICE_DEV guide!

---

## 4. Testing and Validation

### Check Phoneme Coverage

In the **Units** tab:
- The banner shows "missing steady" if any steady-capable phonemes lack sustains
- All diphones should appear in the tree

### Test G2P

Theres a special GUI to test G2P behavior. g2p_gui allows a developer to pick a language, write words, and convert them to the desired phonemes.

In the piano roll editor (`roll_ui.py`):
1. Load your voice
2. Type lyrics in the target language
3. Check if phonemes are generated correctly
4. Terminal output shows mapping: `[lyrics] 'word' -> p h o n e m e s`

---

## 5. Complete Example: English ARPABET (`en-arpa`)

### `svs/lang/en-arpa.ini`

```ini
[language]
name = en-arpasing

[types]
vowel       = aa ae ah ao aw ax ay eh er ey ih iy ow oy uh uw
nasal       = m n ng
trill       =
fricative   = f v th dh s z sh zh hh
approximant = l r w y
aspirate    =
plosive     = b ch d g jh k p t cl
silence     = sil pau

[voiced]
yes = v dh z zh b d g jh
no  = hh cl

[steady]
yes = l r w y
no  =
```

### `svs/g2p/g2p-en-arpa/dict.txt`

```
'Murica  m er ih k ax
'bout  b aw t
'cause  k ah z
'd  d
'dine  d iy n
'dswounds  d z w uw n d z
'emselves  ax m s eh l v z
'fore  f ao r
'fraid  f r ey d
'ho  hh ow
'kay  k ey
'll  ax l
'low  l ow
'mater  m ey t er
'mong  m ah ng
'n  n
...
```

### `svs/g2p/g2p-en-arpa/phones.txt`

```
aa	vowel
ae	vowel
ah	vowel
ao	vowel
aw	vowel
ay	vowel
ax	vowel
el	vowel
en	vowel
eng	vowel
em	vowel
b	stop
ch	affricate
d	stop
dh	fricative
dr	affricate
dx	stop
eh	vowel
er	vowel
ey	vowel
f	fricative
g	fricative
hh	fricative
ih	vowel
iy	vowel
jh	affricate
k	stop
l	liquid
m	nasal
n	nasal
ng	nasal
ow	vowel
oy	vowel
p	stop
q	stop
r	liquid
_r	liquid
s	fricative
sh	fricative
t	stop
th	fricative
tr	affricate
uh	vowel
uw	vowel
v	fricative
w	semivowel
y	semivowel
z	fricative
zh	fricative
```

### `svs/g2p/g2p-en-arpa/convert.txt`
```
_r r
ax ax
dx d
el l
en n
em n
eng ng
tr t r
dr d r
q gs
```

---

## Troubleshooting

**"missing steady"**: Add sustain recordings for all vowels/nasals in `lang.ini`.

**"unmapped alias"**: Add the alias to `dict.txt` or use phonemes directly.

**Wrong phonemes**: Check `convert.txt` mappings match engine phonemes.

**G2P not loading**: Ensure folder name matches language code (e.g., `g2p-ko` for `ko`).

**Pitch jumps**: Verify diphone coverage includes all CV, VC, and VV combinations.

---

## Resources

- **OpenUtau G2P**: https://github.com/openutau/g2p (for training ML models)
- **IPA Chart**: https://www.ipachart.com/ (phoneme reference)
- **UTAU Wiki**: https://utau.fandom.com/ (voicebank structure)

Once complete, your language is ready for voice synthesis!
