# Changelog

## v0.99 — the folder tree is the whole truth
- **Where a folder sits is who the robot is.** The scan now derives every
  robot's plant/line/name from its folder's location — a stale `robot.json` or
  `backup.json` carried along in a copied tree can no longer teleport a robot
  into the plant/line it lived in years ago (the "I imported my old library
  into one plant folder and robots scattered everywhere else" field bug). A
  robot's home folder (the one carrying its sidecar id) always outranks a
  stray old-named copy.
- **`robot.json` no longer stores identity at all** (schema 2). The sidecar
  carries the stable id + config — IPs, FTP user, model, F-number, notes,
  aliases — and never plant/line/name: the folder hierarchy is the only
  source of that truth, so there is no second copy to go stale or fight the
  tree. Legacy schema-1 identity fields are ignored on read and shed whenever
  a sidecar is rewritten; a folder is recognized as a robot by the sidecar
  file's presence. (In-app renames still record the old name as an alias on
  the entry, so stray old-named folders keep re-merging.)
- **Empty folders are real structure.** An empty folder at the library root
  shows as a plant, an empty folder inside a plant as a line, and a folder at
  robot depth — even completely empty — as a robot with "no backup". Build
  your building's skeleton in Explorer, see it in the library, back it up
  from there.
- **Imported 2-digit-year snapshots recognized.** ERBU-era dated backups
  (`YY_MM_DD/HH_MM_SS`) group under their robot like the app's own snapshots
  (and sort/merge correctly) instead of spawning one pseudo-robot per date.
- **Merges need evidence, not a matching name.** Fix-names now confirms two
  entries are the same physical robot before suggesting a merge, using the
  field checklist: hostname, IP, F-number, master counts. 2+ matching signals
  = suggested (and it says which); exactly 1 = shown deselected with a ⚠ why;
  mismatched F-numbers veto outright (an F-number never changes). The FANUC
  factory hostname ("ROBOT") no longer counts as identity — backups reporting
  it used to merge into any robot that happened to be named ROBOT. Every
  merge row in the preview now has its own checkbox (like renames) plus both
  sides' backup counts, and merge targets prefer the convention-named /
  richer-history side. Merging remains strictly line-scoped.
- **Fix-names shows it's working**: the preview scan (it opens every selected
  robot's backup) now raises the global busy strip — "reading names from
  backups…" — instead of going silent for its longest step.
- **Refreshes stopped flashing.** Library refreshes repaint the robot tree in
  place — the old tree stays on screen until the new one is ready, and your
  scroll position survives. The folder watcher also no longer re-announces a
  change the app itself just made (the second, delayed flash after every
  rename/merge/backup).
- **`tools/apply_ip_list.py`**: stamp a building IP list (`{line: {robot:
  ip}}`) onto the tree as `robot.json` sidecars — dry-run by default, atomic
  writes, undo manifest, and a same-line duplicate-IP report for short-name /
  full-name twin folders.
- **`tools/seed_library.py`**: standalone, zero-dependency script to hand a
  coworker with the robot list — seeds their library (blank or existing) with
  every robot + IP under a plant they choose, expanding names to the plant
  convention (080R01 on line RBB01 → RB080R01B01) and silently skipping
  robots they already have by folder name or by IP.

## v0.98 — files are law (the field-feedback release)
- **The library IS your backup folder.** Every listing reflects the tree: folders
  copied in with Explorer appear (a background watcher refreshes within seconds),
  deleted folders disappear, and re-pointing the library folder shows exactly that
  folder's contents — old entries no longer tag along or lock up. An offline
  network drive still serves the last known library, marked stale, never wiped.
- **Adding a robot creates its real folder** (with `robot.json`, IP included), so
  discovery-added robots on a brand-new line survive rebuilds and PC moves. The
  "from backup" / "bulk from folder" import flows and the Delete button are gone —
  copy backups in / delete them with Explorer; hide covers the everyday case.
  Copied folders carrying a `robot.json` fold into that robot's history — and the
  scan now says so ("2 copied snapshots joined R01").
- **Merge, triple-checked.** The duplicate-skip path verifies file-for-file (both
  directions, byte content) before ever dropping a source copy; missing metadata
  and partial copies are conflicts, never deletions. Cross-volume moves stage in a
  `.__part` folder so a crash can't leave a half-snapshot at a real name. Merge
  keeps the folded robot's IPs/notes/config, and the confirm dialog shows the
  direction with a ⇄ swap button. Fix-names previews every rename first.
- **Never lose work.** Stray clicks can't destroy a half-built theme or typed
  form — dismissing warns first, and theme edits autosave a crash-proof draft
  with a restore offer. Closing the app during a backup asks before cutting it off.
- **The library screen at plant scale.** One sticky toolbar (selection-aware
  backup / hide / fix names / merge + counter) replaces the per-line button rows;
  sort by name, IP, or last backup; the compare picker groups by plant/line;
  discovery asks for plant & line at the add step, with pick-from-existing
  suggestions everywhere you'd otherwise retype them. Scan limits raised for
  plant-scale libraries (and truncation is reported, never silent).
- **Backups visible from every screen.** A global progress strip (aggregate bar,
  per-robot details, cancel) survives navigation and even a reload; slow
  operations show a "working…" pulse, and double-clicks can't run them twice.
- **Settings in one place, scaling that respects your data.** One ⚙ panel
  (appearance / text & scale / library folder). "Text size" now grows the DATA;
  the header/tabs/footer are pinned to a separate "chrome scale" — cranking the
  font no longer swells the chrome until nothing fits. The whole-page zoom (and
  its menu-positioning workarounds) is retired.

## v0.9 — ecosystem shell + backup taker
- **Home menu**: open a backup, add one to the library, or take a new one.
- **Robot library** organized PLANT / LINE / ROBOT, persisted locally; add manually
  or import an existing backup folder.
- **Take a new backup**: connect to a FANUC controller over FTP and pull an
  "all of above" backup (the `MD:` device) into a `Latest`-mirror + dated-history
  tree, with a pre-flight reachability probe and live progress.

## v0.82 — compare polish
- Compare screen: refresh, hide individual entries, persistence, in-place filter;
  dropped binary/metadata-only program changes to declutter.

## v0.8 / v0.81 — trust pass
- Bug-batch correctness pass; added the MH Valves and Payloads views.

## v0.76 — composable primitives
- Extracted pills / segmented / table / frame-card / card-hero-kv / drag into shared
  builders; migrated every tab onto them.

## v0.75 — more data
- System-vars tab, KAREL `.PC` programs, DCS rework, program-to-program hops.

## v0.7 / v0.7.1 — DCS
- DCS tab: verify report, change history, signatures; section menu, drop-down
  details, code-styled safe-I/O logic.

## v0.6 — dashboard + compare
- Overview dashboard cleanup and a compare workflow for verifying programs fast.

## v0.3 — feedback round
- Alarm history, search fixes, IO configuration view, linked scroll-lock.

## v0.1 — first cut
- FANUC robot backup viewer: overview, frames, IO, registers, programs, alarms, files.
