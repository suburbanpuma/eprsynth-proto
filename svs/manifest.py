import configparser
import json
import os
import shutil

from . import langcfg


def create_db(path, name, developer, version, language, groups):
    src = langcfg.template_path(language)
    if not os.path.exists(src):
        raise FileNotFoundError(f"no language template for '{language}': {src}")
    os.makedirs(path, exist_ok=True)
    cp = configparser.ConfigParser()
    cp["singer"] = {"name": name, "developer": developer, "version": version,
                    "language": language, "styles": "base"}
    cp["pitchgroups.base"] = {"groups": ", ".join(groups)}
    with open(os.path.join(path, "manifest.ini"), "w") as f:
        cp.write(f)
    shutil.copyfile(src, os.path.join(path, "lang.ini"))
    for g in groups:
        os.makedirs(os.path.join(path, "base", g, "diphones"), exist_ok=True)
        os.makedirs(os.path.join(path, "base", g, "steady"), exist_ok=True)
        if not os.path.exists(os.path.join(path, "base", g, "index.json")):
            with open(os.path.join(path, "base", g, "index.json"), "w") as f:
                json.dump({"units": {}, "steady": {}}, f)


def load_manifest(path):
    cp = configparser.ConfigParser()
    cp.read(os.path.join(path, "manifest.ini"))
    return cp