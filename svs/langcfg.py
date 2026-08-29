import configparser
import os

TYPES = ["vowel", "nasal", "trill", "fricative", "approximant",
         "aspirate", "plosive", "silence"]
DEFAULT_VOICED = {"vowel", "nasal", "trill", "approximant"}
DEFAULT_STEADY = {"vowel", "nasal"}
LANG_DIR = os.path.join(os.path.dirname(__file__), "lang")

class LangConfig:
    def __init__(self, name, ptype, voiced, steady):
        self.name = name
        self._type, self._voiced, self._steady = ptype, voiced, steady

    def phonemes(self): return set(self._type)
    def type(self, ph):   return self._type.get(ph)
    def voiced(self, ph): return self._voiced.get(ph, False)
    def steady(self, ph): return self._steady.get(ph, False)
    def vowels(self):     return sorted(p for p, t in self._type.items() if t == "vowel")

def template_path(language):
    return os.path.join(LANG_DIR, language + ".ini")

def list_templates():
    return sorted(os.path.splitext(f)[0] for f in os.listdir(LANG_DIR)
                  if f.endswith(".ini"))

def load_lang(path):
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    name = cp.get("language", "name", fallback=os.path.basename(path))
    ptype, voiced, steady = {}, {}, {}
    for t in TYPES:
        for p in cp.get("types", t, fallback="").split():
            ptype[p] = t
            voiced[p] = t in DEFAULT_VOICED
            steady[p] = t in DEFAULT_STEADY
    for p in cp.get("voiced", "yes", fallback="").split(): voiced[p] = True
    for p in cp.get("voiced", "no",  fallback="").split(): voiced[p] = False
    for p in cp.get("steady", "yes", fallback="").split(): steady[p] = True
    for p in cp.get("steady", "no",  fallback="").split(): steady[p] = False
    return LangConfig(name, ptype, voiced, steady)

def lang_for_db(db_path):
    """DB-bundled lang.ini wins; else the package template for the manifest language."""
    p = os.path.join(db_path, "lang.ini")
    if os.path.exists(p):
        return load_lang(p)
    cp = configparser.ConfigParser()
    cp.read(os.path.join(db_path, "manifest.ini"))
    return load_lang(template_path(cp["singer"]["language"]))