# BackupViewer — roadmap

Where the project is headed, so parallel work doesn't collide. If you want to
pick something up, say so first (issue, message, whatever works) — claiming a
lane beats discovering two half-built versions of it. Ground rules for *how*
to build any of this live in [CLAUDE.md](CLAUDE.md); what already shipped is
in [CHANGELOG.md](CHANGELOG.md).

Legend: ✅ shipped · 🔨 being built · 📋 decided, not started · ❓ open question

## Recently landed

- ✅ **1.0** — library-first shell, history/time-travel compare, fleet health
  scan, backup integrity (complete-marker), manage-backups tooling.
- ✅ **1.1** — the 3D View tab: DCS cartesian zones drawn to scale, free
  turntable orbit + viewport cube, ortho/perspective, per-zone show/hide with
  pendant-style detail.
- ✅ **LibraryImporter 0.1** — standalone hand-out seeder (robots.json → library
  skeleton), built with a parser seam so it can absorb into the app later.

## 1.x train — small, mostly independent slices

Each of these is deliberately scoped to land on its own. Good places to start.

- 📋 **Report export** — CSV per table, self-contained HTML report, print-to-PDF.
- 📋 **Browser-style tabs** — several backups open at once, drag a tab out to a
  floating window. Architectural note: requires the per-session refactor
  (`_sessions` dict); the compare `side` parameter is trailing-positional —
  see CLAUDE.md before touching endpoint signatures.
- 📋 **More scan checks** — simulated-IO-left-on, general override < 100%,
  alarm-frequency summary, controller clock drift, uninitialized PRs
  referenced by programs.
- 📋 **Golden-robot compare** — pick a reference robot; the scan flags every
  deviation from it across a line.
- 📋 **First-run tips + in-app help** — bundled docs (plant PCs are offline),
  empty-state guidance.
- 📋 **UI scaling audit + XXL preset** — raise the current 24px/160% caps
  without layouts collapsing; probe-gated at the extremes.
- 📋 **Auto-update check** — quiet "newer release exists" toast (GitHub
  releases ping, fully offline-tolerant).
- 📋 **Library-wide content search** — "which robots call PROG_X / use R[57] /
  reference DI[279]" across the whole library, not just the open backup.
- 📋 **Absorb `tools/restyle.py`** — the style-clone kit builder gets UI inside
  the app.
- ❓ **Scheduled backups + retention** — nightly fleet backup reusing the run
  log / retry / complete-marker machinery; needs a keep-last-N + monthly
  retention policy before it's safe to leave running.

## 3D View follow-ups

- 🔨 **Robot models in the viewport** — user-imported models, stored locally,
  matched to robots by model string (one import covers every robot of that
  type; the exe ships zero meshes). The vendor `.rmd` model-pack format is
  reverse-engineering-in-progress: uncompressed sectioned binary, per-part
  float arrays mapped, record alignment + units still open. Fallbacks:
  per-link convex hulls, or STL import if an export path exists.
- 📋 **Static pose first** — a mesh at the base gives fence-vs-robot context;
  posing the arm needs joint angles + per-link kinematics (much later).
- 📋 **Program points in 3D** — plot a program's Cartesian positions among the
  zones (compose their UFRAME); joint-rep points need forward kinematics —
  out of scope for the first pass.
- 📋 **Compare overlay** — ghost the comparison backup's zones into the
  viewport (the "what changed in DCS" killer view).
- ❓ **Lines-mode zones** — DCS `$MODE` values beyond the two ground-truthed
  ones are unmapped; needs a real backup containing a polygon (Lines) zone.

## Cameras — Keyence / Matrox (owned lane, in progress elsewhere)

Attach vision devices to robot entries; open a robot, see its cameras;
one click backs up the robot + all its cameras together.

- 🔨 **Discovery** — agreed direction: probe the DesignAssistant web portal
  (:80/:443) and EtherNet/IP ListIdentity (UDP 44818, Matrox vendor ID) for
  the newer Iris GTX — the old FTP/SMB port gates only find Keyence CV-X and
  the older GTR.
- 🔨 **GTX backup transport** — SSH/SFTP (or a DA HTTP export), not SMB; SMB
  stays as the GTR fallback. Blocked on a live credentials/endpoint spike.
- 📋 **Data model** — cameras link to a robot via sidecar *config* (a parent
  id), never by folder identity; group backup fans out to per-device jobs and
  reuses the complete-marker / run-log / retry machinery per device.
- ❓ **Shared cameras** — can one camera serve two robots? Decides whether the
  link is single-parent or a list.

## DCDL importer

- 📋 Absorb LibraryImporter into the viewer as an import wizard (the parser
  seam in `libraryimporter/core.py` exists for this).
- 📋 Parse a raw DCDL (site-wide device/IP list) directly: generate the robot
  *and camera* lists from it. Re-import is a **suggest-only diff** (new /
  retired / changed-IP) — never destructive.
- ❓ Needs a sample DCDL to pin the file format.

## 2.0 — editing (the headline)

Decided principles (these are settled — build against them):

- 📋 **Never soil the backup.** Backups stay read-only evidence; edits live in
  a sibling workspace (overlay). The review-your-edits screen is the existing
  compare engine pointed at original vs overlay.
- 📋 **Apply paths, not binaries.** Programs export as edited `.LS` (text).
  Register/PR/frame values export as a generated one-shot APPLY program of
  literal assignments — reviewable on the pendant, version-proof. Comments
  (register names, IO) push live via the controller's web comment hook when
  on the network. No synthesizing `.TP`/`.SV`/`.VR` binaries.
- 📋 **USB-export-first.** Deploy = a named folder on a USB stick with a
  manifest + step-by-step pendant checklist. Direct FTP write-back comes
  later as a separately gated, human-in-the-loop tier — many sites prohibit
  it, and it must never be the default.
- 📋 **DCS stays read/diff-only.** The viewer will not emit DCS payloads; the
  pendant's apply/code/signature flow is the controlled path for safety
  parameters, full stop.
- ❓ Open spikes: ASCII-upload option coverage on real fleets, the web comment
  hook's availability per controller generation, macro-table writability
  inventory, edits-workspace schema.

## Parking lot (real, but not next)

Live view (poll a robot over FTP without taking a backup) · multi-vendor
parsing (KUKA/Kawasaki — formats share almost nothing) · plotting a second
robot's zones in one viewport · anything requiring WebGL (SVG stays the
floor because rescue-mode PCs render in software).
