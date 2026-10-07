# Routing rules

**You write this file before Stage 6.** These are policy choices about which mistakes are acceptable, so they're yours, not Claude's. The router code reads this file.

Think in costs: a dangerous answer marked safe (a miss) costs far more than a safe answer sent to review (a false alarm).

## Auto-fail

Fill in. Starting questions:

- Which rule failures are always a fail?
- What judge scores make an answer fail without human review?
- Do critical auto-fails still go to a person to confirm?

## Human review

Fill in. Starting questions:

- Which risk levels always go to review, whatever the scores?
- What counts as the judges disagreeing (any metric? safety only? by how much)?
- Does a single `unsure` send a case to review?
- Do trap cases always go to review?

## Auto-pass

Fill in. Starting questions:

- Which risk levels can ever auto-pass?
- Must both judges agree? On every metric?

## Random audit

What share of auto-passed answers goes to review anyway, so you can find what the system misses?

## Review capacity

How many cases can one person review per run? If the router sends more, what gets priority (severity × uncertainty × novelty)?
