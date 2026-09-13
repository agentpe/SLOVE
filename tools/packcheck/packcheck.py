#!/usr/bin/env python3
"""SLO VE voice pack checker.

Answers the one question a pack author cannot answer by looking at their own
folders: which of my folders can SLO VE actually reach?

It reads SLO VE's own call sites (SLOVE_Voice.psc) and resolution config
(SLOVE_voices.toml), replays AudioUtil's resolution for every spoken beat in
the engine against YOUR folder list, and reports three things:

  1. NAME MISMATCHES  - a beat that lands outside your pack while you ship a
                        folder that is obviously the same beat under another
                        name. These are bugs; every one of the thirteen fixed
                        in SLO VE 0.6.15 shows up here.
  2. UNREACHED BEATS  - beats that leave your pack and you have nothing close.
                        Normal: you simply do not voice that beat.
  3. DEAD FOLDERS     - folders you ship that nothing can ever request, and
                        folders with no audio in them at all.

Requires Python 3.11+ (tomllib). Nothing else.

    python packcheck.py "C:\\path\\to\\My IVDT Pack"
    python packcheck.py "...\\Sound\\fx\\SLOVE\\MyVoice" --slove "E:\\mods\\SLO VE"

Exit code 1 if anything in group 1 or 3 was reported, so it can gate a build.
"""

import argparse
import difflib
import glob
import os
import re
import sys
from collections import defaultdict

import tomllib

MAX_FALLBACK_HOPS = 8        # AudioUtil's kMaxCategoryFallbackHops
PACK = '(your pack)'         # stands in for the pack's own slot id in the chain
AUDIO_EXT = ('.wav', '.xwm', '.fuz')


def norm(text):
    """AudioUtil's Config::Normalize - lowercase, drop everything non-alphanumeric."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def tokens(text):
    """Split an identifier or folder name into lowercase words, for the did-you-mean pass."""
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text)
    return [t for t in re.split(r'[^A-Za-z0-9]+', spaced.lower()) if t]


# --------------------------------------------------------------------------
# locating SLO VE's own files
# --------------------------------------------------------------------------

def find_slove(explicit):
    """Return (SLOVE_Voice.psc, SLOVE_voices.toml).

    Works against a checkout (the repo this tool lives in) or an INSTALLED
    SLO VE - it ships both its script sources and its config, so a pack author
    can point at their mod folder instead of cloning anything.
    """
    roots = []
    if explicit:
        roots.append(explicit)
    here = os.path.dirname(os.path.abspath(__file__))
    roots.append(os.path.normpath(os.path.join(here, '..', '..')))  # tools/packcheck/../..

    for root in roots:
        pscs = (os.path.join(root, 'papyrus', 'Source', 'SLOVE_Voice.psc'),
                os.path.join(root, 'dist', 'Scripts', 'Source', 'SLOVE_Voice.psc'),
                os.path.join(root, 'Scripts', 'Source', 'SLOVE_Voice.psc'))
        tomls = (os.path.join(root, 'dist', 'SKSE', 'Plugins', 'AudioUtil', 'config', 'SLOVE_voices.toml'),
                 os.path.join(root, 'SKSE', 'Plugins', 'AudioUtil', 'config', 'SLOVE_voices.toml'))
        psc = next((p for p in pscs if os.path.isfile(p)), None)
        toml = next((t for t in tomls if os.path.isfile(t)), None)
        if psc and toml:
            return psc, toml
    sys.exit("could not find SLOVE_Voice.psc + SLOVE_voices.toml.\n"
             "Run this from inside the SLO VE repo, or pass --slove <your installed SLO VE folder>.")


# --------------------------------------------------------------------------
# locating the pack's voice folder
# --------------------------------------------------------------------------

def find_pack(path):
    """Return (voice_folder, {slot id: fallback slot}, variation).

    Accepts either the pack root (finds its AudioUtil overlay and follows the
    slot's `path`) or the voice folder itself.

    A pack ships ONE overlay PER INSTALLABLE SLOT - Slot_PC, Slot_F2 .. Slot_F10 -
    all pointing at the same audio, and the installer picks one. Their fallbacks
    are not necessarily the same (the PC slot backs onto F0, pool slots onto F0B,
    and the two stock slots need not list the same categories), so which slot you
    installed into can change what reaches your pack. The caller chooses; letting
    directory order decide it silently would be a coin flip.
    """
    if not os.path.isdir(path):
        sys.exit("not a folder: " + path)

    ids, found = {}, {}
    overlays = glob.glob(os.path.join(path, '**', 'SKSE', 'Plugins', 'AudioUtil', 'config', '*.toml'),
                         recursive=True)
    for overlay in sorted(overlays):
        try:
            with open(overlay, 'rb') as handle:
                cfg = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for slot in cfg.get('slot', []):
            rel = slot.get('path')
            if not rel:
                continue  # gag slots and the like define categories, not a root
            folder = find_under(path, rel)
            if folder:
                ids.setdefault(folder, {})[slot.get('id', '?')] = norm(slot.get('fallback') or '')
                found[folder] = (slot.get('variation') or 'A').upper()
    if found:
        folder = next(iter(found))
        return folder, ids[folder], found[folder]

    # no overlay found - assume we were handed the voice folder directly
    if any(os.path.isdir(os.path.join(path, e)) for e in os.listdir(path)):
        return path, {'?': 'f0b'}, '?'
    sys.exit("no voice folders found under " + path)


def find_under(root, data_rel):
    """Find the directory under `root` whose tail matches a Data-relative path."""
    tail = os.path.normpath(data_rel.replace('\\', os.sep)).lower()
    for dirpath, _dirnames, _files in os.walk(root):
        if dirpath.lower().endswith(tail):
            return dirpath
    return None


def scan_folders(voice_folder):
    """normalized name -> (display name, clip count)."""
    out = {}
    for entry in sorted(os.listdir(voice_folder)):
        full = os.path.join(voice_folder, entry)
        if not os.path.isdir(full):
            continue
        clips = 0
        for _dirpath, _dirnames, files in os.walk(full):  # tag subfolders count too
            clips += sum(1 for f in files if f.lower().endswith(AUDIO_EXT))
        out[norm(entry)] = (entry, clips)
    return out


# --------------------------------------------------------------------------
# SLO VE's call sites and category maps
# --------------------------------------------------------------------------

def parse_calls(psc_path):
    """Every female-routed PlaySound call: (line, category, debugtext)."""
    with open(psc_path, encoding='utf-8', errors='replace') as handle:
        src = handle.read()
    calls = []
    pattern = re.compile(r'PlaySound\(\s*"([^"]+)"\s*,\s*([A-Za-z_]\w*)(.*?)\)\s*(?:;|$)', re.M)
    for match in pattern.finditer(src):
        category, actor, rest = match.group(1), match.group(2), match.group(3)
        debug = re.search(r'debugtext\s*=\s*"([^"]*)"', rest, re.IGNORECASE)
        voice_actor = re.search(r'voiceActor\s*=\s*([A-Za-z_]\w*)', rest)
        female = 'forceFemaleVoice' in rest or (actor == 'mainFemaleActor' and not voice_actor)
        if female:
            calls.append((src[:match.start()].count('\n') + 1,
                          category,
                          debug.group(1) if debug else 'None'))
    return calls


def load_maps(toml_path):
    """(aliases, category fallbacks, {slot id: (categories, fallback slot)})."""
    with open(toml_path, 'rb') as handle:
        cfg = tomllib.load(handle)
    aliases = {norm(k): v for k, v in cfg.get('category_aliases', {}).get('female', {}).items()}
    fallbacks = {norm(k): v for k, v in cfg.get('category_fallbacks', {}).get('female', {}).items()}
    slots = {}
    for slot in cfg.get('slot', []):
        cats = {norm(k) for k in slot.get('categories', {})}
        slots[norm(slot.get('id', ''))] = (cats, norm(slot.get('fallback') or ''))
    return aliases, fallbacks, slots


# --------------------------------------------------------------------------
# AudioUtil's resolution, replayed against one slot
# --------------------------------------------------------------------------

def resolve_ladder(category, keys, aliases, fallbacks):
    """AudioUtil's within-one-slot resolution: the literal name, then its alias,
    then the same pair at each rung of the category-fallback ladder."""
    def candidates(name):
        options = [name]
        if name in aliases:
            options.append(norm(aliases[name]))
        for key in options:
            if key in keys:
                return key
        return None

    current = norm(category)
    hit = candidates(current)
    if hit:
        return hit
    seen = {current}
    for _hop in range(MAX_FALLBACK_HOPS):
        if current not in fallbacks:
            break
        target = norm(fallbacks[current])
        if target in seen:
            break
        seen.add(target)
        current = target
        hit = candidates(current)
        if hit:
            return hit
    return None


def resolve_chain(category, pack, aliases, fallbacks, slots):
    """Full resolution: the pack's own slot, then its fallback-slot chain.

    Returns (slot id, folder key) or None. `pack` is (keys, fallback slot id);
    the pack's slot is reported as PACK so the caller can tell "played from your
    folders" from "fell through to somebody else's".
    """
    slot_id, (keys, nxt) = PACK, pack
    for _hop in range(4):  # AudioUtil caps the slot chain at 4 hops
        hit = resolve_ladder(category, keys, aliases, fallbacks)
        if hit:
            return slot_id, hit
        if not nxt or nxt not in slots:
            return None
        slot_id = nxt
        keys, nxt = slots[nxt]
    return None


def requested_name(category, debugtext, pack, aliases, fallbacks, slots):
    """What SLO VE actually asks AudioUtil for.

    PlaySound's per-actor Variation-B remap swaps the category for `debugtext`
    when the two DIFFER - debugtext being the B-layout folder name - AND
    CategoryExists says the label resolves. That gate matters: plenty of call
    sites pass a pure log label ("FemaleOrgasm"), which resolves nowhere, so no
    remap happens and the category stands. A call site whose debugtext EQUALS
    its category has opted out of the remap entirely - that is the bug class
    this tool exists to find.
    """
    if debugtext != 'None' and norm(debugtext) != norm(category):
        if resolve_chain(debugtext, pack, aliases, fallbacks, slots):
            return debugtext
    return category


NEGATIONS = ('un', 'non', 'anti', 'no')


def negates(left, right):
    """Is one of these the other with a negating prefix? "Unamused" vs "Amused".

    Spelling similarity cannot tell an inversion from a rename - those two are an
    87% string match and mean the opposite - so a suggestion that would have a
    pack author wire a beat to its own antonym is refused outright.
    """
    for short, long_ in ((left, right), (right, left)):
        for prefix in NEGATIONS:
            if long_ == prefix + short:
                return True
    return False


def did_you_mean(category, folders):
    """A folder that is plainly the same beat under a different name, or None.

    Two ways a rename shows up lexically. Either the category's words all appear
    in the folder name (AskForVaginalCum inside "Male Orgasm Soon Ask For Vaginal
    Cum") - then the closest fit is the one with the fewest extra words - or the
    two spellings are near-identical ("Penetrative..." vs "Penetrated...").

    Deliberately does NOT skip folders other beats already reach: a folder being
    reachable from somewhere else says nothing about whether it is the right
    answer here, and skipping them hid every real mismatch behind a worse match.

    Purely lexical, so a SEMANTIC rename (CameInMouth -> "Ending Orgasmed Inside
    Mouth") will not be found. The DEAD FOLDERS section is the backstop for those.
    """
    cat_tokens = set(tokens(category))
    best, best_rank = None, None
    for key, (display, clips) in folders.items():
        if clips == 0:
            continue
        folder_tokens = set(tokens(display))
        # one shared word is not evidence ("Orgasm" vs "Orgasm Over The Top")
        subset = len(cat_tokens) >= 2 and cat_tokens <= folder_tokens
        ratio = difflib.SequenceMatcher(None, norm(category), key).ratio()
        if subset:
            rank = (2, -len(folder_tokens - cat_tokens), ratio)
        elif ratio >= 0.75:
            differing = (cat_tokens ^ folder_tokens)
            if any(negates(a, b) for a in differing for b in differing if a != b):
                continue
            if negates(norm(category), key):
                continue
            rank = (1, 0, ratio)
        else:
            continue
        if best_rank is None or rank > best_rank:
            best, best_rank = display, rank
    return best


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check which SLO VE voice beats can actually reach your pack.")
    parser.add_argument('pack', help="your pack's root folder, or its Sound\\fx\\SLOVE\\<Name> folder")
    parser.add_argument('--slove', help="an installed SLO VE folder (default: this repo)")
    parser.add_argument('--slot',
                        help="which slot to check the pack as, when it ships several "
                             "(they can back onto different stock slots)")
    parser.add_argument('--all', action='store_true',
                        help="also list every unreached beat, not just the suspected mismatches")
    args = parser.parse_args()

    psc_path, toml_path = find_slove(args.slove)
    voice_folder, slot_fallbacks, variation = find_pack(args.pack)
    chosen = args.slot or sorted(slot_fallbacks)[0]
    if chosen not in slot_fallbacks:
        sys.exit("this pack ships no slot {!r} - it offers: {}".format(
            chosen, ', '.join(sorted(slot_fallbacks))))
    fallback_slot = slot_fallbacks[chosen]
    folders = scan_folders(voice_folder)
    aliases, fallbacks, slots = load_maps(toml_path)
    calls = parse_calls(psc_path)
    pack = (set(folders), fallback_slot)

    reached, unreached, went_to = set(), defaultdict(list), {}
    for line, category, debugtext in calls:
        name = requested_name(category, debugtext, pack, aliases, fallbacks, slots)
        landed = resolve_chain(name, pack, aliases, fallbacks, slots)
        if landed and landed[0] == PACK:
            reached.add(landed[1])
        else:
            unreached[category].append(line)
            went_to[category] = landed[0].upper() if landed else "nothing at all"

    clips = sum(count for _name, count in folders.values())
    others = sorted(set(slot_fallbacks) - {chosen})
    print("SLO VE pack check - as slot {} (backs onto {}), variation {}".format(
        chosen, fallback_slot.upper() or "nothing", variation))
    if others:
        print("  this pack also installs as {} - re-run with --slot to check those".format(
            ', '.join(others)))
    print("  " + voice_folder)
    print("  {} folders, {} clips".format(len(folders), clips))
    print("  against {} spoken call sites in SLOVE_Voice.psc".format(len(calls)))
    print()

    mismatches, plain = [], []
    for category, lines in sorted(unreached.items()):
        suggestion = did_you_mean(category, folders)
        (mismatches if suggestion else plain).append((category, lines, suggestion))

    problems = 0

    if mismatches:
        problems += len(mismatches)
        print("SUSPECTED NAME MISMATCH ({}) - check each of these".format(len(mismatches)))
        print("  SLO VE asks for a name your pack does not use, while you ship a folder")
        print("  that looks like the same beat. The line plays somebody else's audio.")
        print("  The suggested folder is a guess from the name alone - you know which")
        print("  of your folders that beat belongs in.")
        for category, lines, suggestion in mismatches:
            more = " +{} more".format(len(lines) - 1) if len(lines) > 1 else ""
            print("    {}".format(category))
            print("        you ship '{}' - plays {} instead".format(suggestion, went_to[category]))
            print("        asked at SLOVE_Voice.psc:{}{}".format(lines[0], more))
        print()

    dead = [(display, count)
            for key, (display, count) in sorted(folders.items(), key=lambda kv: kv[1][0].lower())
            if key not in reached or count == 0]
    if dead:
        problems += len(dead)
        print("DEAD FOLDERS ({}) - shipped but never heard".format(len(dead)))
        for display, count in dead:
            why = "no clips in it" if count == 0 else "nothing ever requests it"
            print("    '{}'  ({} clips) - {}".format(display, count, why))
        print()

    if plain:
        print("NOT VOICED BY THIS PACK ({}) - normal, you ship nothing close".format(len(plain)))
        if args.all:
            for category, lines, _suggestion in plain:
                print("    {}  -> {}  (SLOVE_Voice.psc:{})".format(
                    category, went_to[category], lines[0]))
        else:
            print("    re-run with --all to list them")
        print()

    if problems:
        print("{} thing(s) worth a look.".format(problems))
    else:
        print("Nothing to flag - every beat you ship a folder for is reachable.")
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
