# Checking Your Pack

You can look at your own folders all day and still not know the thing that
matters: **which of them can SLO VE actually reach?** A folder is only heard if
some call site in the engine asks for a name that resolves to it — and when it
doesn't, nothing breaks. The line plays a stock SexLab moan and sounds like a
beat you simply didn't record.

That is how thirteen beats went unheard for months before SLO VE 0.6.15.

`packcheck` answers the question offline, before you ship.

## Running it

Needs **Python 3.11+** and nothing else.

```
python tools/packcheck/packcheck.py "C:\path\to\My IVDT Pack"
```

Point it at your pack's root — it finds your `[[slot]]` overlay, follows the
slot's `path` to your audio, and reads your `variation` and `fallback`. You can
also hand it the voice folder itself.

Your pack ships one overlay per installable slot — `Slot_PC`, `Slot_F2` … `Slot_F10`
— and they don't all back onto the same stock slot, so which one you installed
into can change what reaches you. The tool checks the first and names the rest:

```
SLO VE pack check - as slot F1 (backs onto F0), variation B
  this pack also installs as F2, F3 ... - re-run with --slot to check those
```

If you're not working from a SLO VE checkout, point it at your installed copy
(SLO VE ships both its script sources and its config, so an installed mod folder
is enough):

```
python packcheck.py "C:\path\to\My Pack" --slove "E:\mods\SLO VE"
```

## Reading the report

```
SLO VE pack check - slot F2, variation B
  ...\Core\Sound\fx\SLOVE\MyVoice
  70 folders, 778 clips
  against 256 spoken call sites in SLOVE_Voice.psc
```

### Suspected name mismatch

```
SUSPECTED NAME MISMATCH (1) - check each of these
    PenetrativeCommentsIntense
        you ship 'Penetrated Comments Intense' - plays F0 instead
        asked at SLOVE_Voice.psc:2105 +2 more
```

SLO VE asks for a name your pack doesn't use, while you ship a folder that looks
like the same beat. **These are the ones to act on.** Either rename your folder
to what the engine asks for, or — if the engine is the one that's wrong — open an
issue, because a bridge belongs in `[category_fallbacks.female]` so it fixes
every pack at once.

The suggested folder is a guess from the name alone. You know which of your
folders the beat belongs in; the tool only knows spelling.

### Dead folders

```
DEAD FOLDERS (4) - shipped but never heard
    'Penetrated Comments Victim Intense'  (11 clips) - nothing ever requests it
    'Kissing'  (0 clips) - no clips in it
```

Audio you recorded that nothing can ever play. Two causes: the folder is empty,
or no call site in the engine requests that beat (yet). The second kind is worth
reporting — it usually means the engine has a gap, not your pack.

This section is the backstop for renames the name-matching can't see. `CameInMouth`
and `Ending Orgasmed Inside Mouth` are the same beat, and no amount of spelling
comparison will say so — but the folder showing up dead will.

### Not voiced by this pack

Beats that leave your pack and have nothing close to them in it. Completely
normal — no pack voices every beat. `--all` lists them with the slot each one
falls through to, which is a reasonable shopping list if you want to record more.

## Exit code

`1` if anything in the first or second section was reported, `0` if not, so you
can wire it into your own build.
