# eprsynth-proto
concatenative synthesizer based on the og papers that led to vocaloid 1. vibecoded with qwen3.8-max...
---
# usage

macos: 

piano roll
python3 -m svs.roll_ui

devkit
python3 -m svs.gui

g2p tester
python3 -m svs.g2p_gui

epr modeling tester
python3 -m svs.epr_gui

concatenator tester
python3 -m svs.test_gui


frontend guis:

epr_gui.py: loose wav epr modeler. supports lab+lang for guided models

g2p_gui.py: openutau g2p model tester.

gui.py: devkit

roll_ui.py: editor

test_gui: core sample concatenating test, no params

config.py: configs for modeling/default parameters/synthesis
