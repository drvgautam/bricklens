# 0005 — Synthetic ground truth first, public dataset second

**Status:** accepted · **Sprint:** 5

## Decision
Primary validation runs on a synthetic generator with 15 scripted faults and exact ground truth; the public CSIRO
AHU dataset is the second run. Perfect synthetic scores are the expected baseline and are reported as such.

## Why
Exact labels make precision/recall/localisation unambiguous and give CI a hard gate. Public FDD datasets have coarse
labels (day-long fault episodes), missing point types, and — for CSIRO — Git LFS hosting that was unreachable from
the development sandbox; they are the right place to *learn* where the detectors are weak, not to gate a build.

## Consequences
`docs/validation.md` states plainly what the synthetic run does and does not establish; the CSIRO run has a
recipe and a mapping template but is not yet executed.
