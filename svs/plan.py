# =============================================================================
# plan.py — MicroScore layer 1, priority-based timing:
#   1) c-v diphone P2 locked to the note onset by default, movable via
#      note.ov["c<v>"][0];
#   2) sustain stays INSIDE the note: [c-v end, min(note end, next chain head)];
#   3) v-c / c-c rows = half the c-v length (2:1), squeezed proportionally
#      into the space before the c-v consonant lead;
#   4) FAST PASSAGES: the c-v row (and chain rows) shrink so everything ends
#      inside the note — articulations follow the score timing;
#   5) target = first true vowel; consonant sustains only when the note is
#      that single phoneme; pre-onset chain rows sing at the PREVIOUS note's
#      pitch so portamento stays the only pitch move;
#   6) categories from db.lang (steady() == vowel-like).
#   7) Rows carry `pmidi` (pitch before the split) and `split` (ms within the
#      row where the pitch target switches) so synth.row_frames can pin the
#      pre-onset consonant to the previous pitch under MODULATION.
#   Defaults BPM-adjusted (c-v = beat/2); overrides in note.ov (key -> [p2,
#   end]); note.chain the chain head; note.pre the first head; note.rel the
#   final release.
# =============================================================================

def _unit_info(db, pair, midi):
    try:
        _a, meta, _g = db.unit(pair, midi)
        mk = meta["markers"]
        return float(mk.get("p2", 0.)), float(mk.get("end", 0.))
    except KeyError:
        return 0., 0.


def plan(db, notes, beat=None):
    rows, layout = [], []
    notes = sorted(notes, key=lambda n: n.start)
    N = len(notes)

    # ---------------- pass 1: chain geometry per note ----------------
    meta = []
    prev_cv_end = None
    for i, n in enumerate(notes):
        ps = n.phonemes
        # target = first true vowel; else first steady-capable phoneme
        v = next((j for j, p in enumerate(ps) if db.lang.type(p) == "vowel"), -1) if ps else -1
        if v < 0:
            v = next((j for j, p in enumerate(ps) if db.lang.steady(p)), 0) if ps else 0
        prev = notes[i - 1].phonemes[-1] if i and notes[i - 1].phonemes else "sil"
        src_cv = prev if v == 0 else ps[v - 1]
        ov = getattr(n, "ov", None) or {}
        E = n.start + n.dur

        # c-v row length (P2 part ratio 1:2), override-able
        if beat is not None:
            Lcv = max(60., beat / 2.)
        else:
            Lcv = max(40., _unit_info(db, f"{src_cv} {ps[v]}", n.midi)[1])
        o = ov.get(f"c{v}")
        if o and o[1] is not None: Lcv = max(40., o[1])
        p1_cv = Lcv / 3.

        # preceding chain rows: VC = half of CV (weights for the squeeze)
        pre = []
        for j in range(v):
            src = prev if j == 0 else ps[j - 1]
            t = (Lcv / 2. if beat is not None
                 else max(40., _unit_info(db, f"{src} {ps[j]}", n.midi)[1]))
            oj = ov.get(f"c{j}")
            if oj and oj[1] is not None: t = max(40., oj[1])
            pre.append([src, ps[j], t])

        lo = prev_cv_end if (i > 0 and prev_cv_end is not None) else -1e9
        if i > 0:
            # P2 locked to the onset; never overlap the previous c-v end
            cv_start = max(n.start - p1_cv, lo)
            room = E - cv_start
            if Lcv > room:                       # fast passage: fit inside note
                Lcv = max(60., room)
                p1_cv = Lcv / 3.
                cv_start = max(n.start - p1_cv, lo)
            sumb = sum(p[2] for p in pre)
            head = cv_start - sumb
            if head < lo: head = lo
            if n.chain is not None:              # manual head override
                head = min(max(n.start + n.chain, lo), cv_start)
        else:
            head = n.start + (getattr(n, "pre", None) or 0.)
            sumb = sum(p[2] for p in pre)
            room = E - (head + sumb)
            if Lcv > room:
                Lcv = max(60., room)
                p1_cv = Lcv / 3.
            cv_start = head + sumb

        # boundary ladder: chain space distributed proportionally (monotonic)
        rb = [head]
        span = max(0., cv_start - head)
        wsum = sum(p[2] for p in pre) or 1.
        acc = head
        for j in range(v):
            acc += span * (pre[j][2] / wsum)
            rb.append(acc)
        rb.append(cv_start + Lcv)

        meta.append(dict(v=v, pre=pre, rb=rb, p1_cv=p1_cv,
                         head=head, src_cv=src_cv))
        prev_cv_end = rb[-1]

    # ---------------- pass 2: rows + layout ----------------
    for i, n in enumerate(notes):
        ps = n.phonemes
        if not ps:
            continue
        v, pre, rb = meta[i]["v"], meta[i]["pre"], meta[i]["rb"]
        p1_cv, src_cv = meta[i]["p1_cv"], meta[i]["src_cv"]
        E = n.start + n.dur
        sus_end = min(E, meta[i + 1]["head"]) if i + 1 < N else \
            (n.start + n.rel if n.rel is not None else E)   # sustain IN the note
        ov = getattr(n, "ov", None) or {}

        # chain rows; pre-onset consonants sing at the PREVIOUS note's pitch
        for j in range(v + 1):
            src = pre[j][0] if j < v else src_cv
            length = rb[j + 1] - rb[j]
            if length < 25.:                     # too short to render: skip
                continue
            rowmidi = notes[i - 1].midi if (j < v and i > 0) else n.midi
            # c-v row: before the note onset it must sing the PREVIOUS pitch
            pmidi = (notes[i - 1].midi if i > 0 else n.midi) if j == v else rowmidi
            split = min(max(n.start - rb[j], 0.), length) if j == v else 1e9
            if j < v:
                oj = ov.get(f"c{j}")
                p2 = oj[0] if oj and oj[0] is not None else length * 2. / 3.
            else:
                oj = ov.get(f"c{v}")
                p2 = oj[0] if oj and oj[0] is not None else p1_cv
            rows.append(dict(pair=f"{src} {ps[j]}", dur=length, midi=rowmidi,
                             s=rb[j], e=rb[j + 1],
                             lkey=("chain", i) if (j == 0 and i > 0) else None,
                             p2=min(max(p2, 20.), length - 20.),
                             resizable=j < v, ni=i, rk=f"c{j}",
                             pmidi=pmidi, split=split))

        # phoneme-lane blocks
        sil_first = bool(v == 0 and src_cv == "sil") or (v > 0 and pre[0][0] == "sil")
        if sil_first:
            layout.append(dict(label="sil", s=rb[0], e=rb[1], lkey=None))
        for j in range(v):
            if sil_first:
                s, e = rb[j + 1], rb[j + 2]
            else:
                s = rb[j]
                e = (rb[2] if v == 1 else rb[1]) if j == 0 else \
                    (rb[j + 2] if j == v - 1 else rb[1])
            layout.append(dict(label=ps[j], s=s, e=e,
                               lkey=("chain", i) if j == 0 else None))
        if v == 0 and not sil_first:
            layout.append(dict(label=ps[0], s=rb[0], e=rb[1], lkey=("chain", i)))

        # vowel sustain + internal phonemes
        ons = list(n.onsets) + [0.] * (len(ps) - len(n.onsets))
        t = rb[v + 1]
        for j in range(v, len(ps)):
            if j + 1 < len(ps):
                lead2, rec2 = _unit_info(db, f"{ps[j]} {ps[j+1]}", n.midi)
                oij = ov.get(f"i{j+1}")
                if oij and oij[1] is not None: rec2 = max(40., oij[1])
                if oij and oij[0] is not None: lead2 = min(max(oij[0], 20.), rec2 - 20.)
                end = min(sus_end, max(t + 40., n.start + ons[j + 1] - lead2))
            else:
                end = sus_end
            if end > t:
                # vowel sustains always; consonant (nasal) sustains ONLY when
                # the note is exactly that single phoneme
                if db.lang.type(ps[j]) == "vowel" or \
                        (len(ps) == 1 and db.lang.steady(ps[j])):
                    rows.append(dict(pair=ps[j], dur=end - t, midi=n.midi, s=t, e=end,
                                     lkey=("vow", i, f"c{v}", rb[v]) if j == v else None,
                                     pmidi=n.midi, split=0.))
                    layout.append(dict(label=ps[j], s=t, e=end,
                                       lkey=("vow", i, f"c{v}", rb[v]) if j == v else None))
                    t = end
            if j + 1 < len(ps):
                lead2, rec2 = _unit_info(db, f"{ps[j]} {ps[j+1]}", n.midi)
                oij = ov.get(f"i{j+1}")
                if oij and oij[1] is not None: rec2 = max(40., oij[1])
                if oij and oij[0] is not None: lead2 = min(max(oij[0], 20.), rec2 - 20.)
                st2 = max(t + 40., n.start + ons[j + 1] - lead2)
                rec2 = min(rec2, max(40., E - st2))      # fit inside the note
                rows.append(dict(pair=f"{ps[j]} {ps[j+1]}", dur=rec2, midi=n.midi,
                                 s=st2, e=st2 + rec2, lkey=("onset", i, j + 1, lead2),
                                 p2=lead2, resizable=True, ni=i, rk=f"i{j+1}",
                                 pmidi=n.midi, split=0.))
                layout.append(dict(label=ps[j + 1], s=st2, e=st2 + rec2,
                                   lkey=("onset", i, j + 1, lead2)))
                t = st2 + rec2

        if i == N - 1:
            rel_p2, rel_rec = _unit_info(db, f"{ps[-1]} sil", n.midi)
            orr = ov.get("rel")
            if orr and orr[1] is not None: rel_rec = max(40., orr[1])
            if orr and orr[0] is not None: rel_p2 = min(max(orr[0], 20.), rel_rec - 20.)
            rows.append(dict(pair=f"{ps[-1]} sil", dur=rel_rec, midi=n.midi,
                             s=t, e=t + rel_rec, lkey=("rel", i),
                             p2=rel_p2, resizable=True, ni=i, rk="rel",
                             pmidi=n.midi, split=0.))
            layout.append(dict(label="sil", s=t, e=t + rel_rec, lkey=("rel", i)))

    return rows, layout