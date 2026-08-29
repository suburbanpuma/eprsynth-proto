import argparse
from . import core

def main():
    ap = argparse.ArgumentParser("svs dev tool")
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("create-db")
    c.add_argument("--db", required=True); c.add_argument("--name", required=True)
    c.add_argument("--developer", required=True); c.add_argument("--version", default="1.0.0")
    c.add_argument("--language", default="ja"); c.add_argument("--groups", nargs="+", required=True)
    i = sp.add_parser("import")
    i.add_argument("--db", required=True); i.add_argument("--group", required=True)
    i.add_argument("--wav", required=True); i.add_argument("--labels", required=True)
    r = sp.add_parser("report"); r.add_argument("--db", required=True)
    a = ap.parse_args()
    if a.cmd == "create-db":
        core.create_db(a.db, a.name, a.developer, a.version, a.language, a.groups)
    elif a.cmd == "import":
        core.import_recording(a.db, a.group, a.wav, a.labels)
    else:
        info, inv = core.inventory(a.db)
        for g, (idx, missing) in inv.items():
            print(f"[{g}] units={len(idx['units'])} steady={len(idx['steady'])}")
            for pair, m in sorted(idx["units"].items()):
                print(f"   {pair:10s} F0={m['rec_pitch']:6.1f}  F1..3={[round(v) for v in m['formants']]}")
            if missing: print("   !! missing steady:", missing)

if __name__ == "__main__":
    main()