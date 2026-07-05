# Stage 0 Known Limitations

- **`rvol_120m_hist*` missing rate ~65%.** The same-time-of-day historical
  lookup for the 120-minute RVOL windows frequently finds too few (or zero)
  prior-session observations at that exact clock-aligned bucket, because
  120-minute buckets are anchored to fixed clock times (00:00, 02:00, ...)
  rather than to the research session's own 18:00 start, so the bucket a
  touch falls into often has a sparse history of matching same-time-of-day
  volume. The 30- and 60-minute RVOL windows have a much lower missing rate
  (5-7%). If RVOL enters Stage 1 candidate formulas, prefer the 30/60-minute
  windows or re-anchor the 120-minute bucket grid to session start before
  relying on it.
- **VXN retrieval pipeline** remains undocumented (hash/row-count verified
  only) -- see `verification/claude-baseline-v1`'s report.
- **Canonical bars file byte-hash** does not reproduce the frozen
  `3d0228fc...` SHA-256, though content is verified identical by every other
  available check (see `verification/claude-baseline-v1`'s
  `VERIFICATION_REPORT.md`). This research branch's bars file carries the
  same content, same caveat.
- **Causal-roll sensitivity series** (contract selection using only the
  previous completed day/session's volume, per the Stage 1 prompt's roll
  caveat) has **not** been built in Stage 0 -- it is a Stage 1 perturbation
  requirement, out of this stage's scope.
- **The 16:00-18:00 ET gap** (137 touches) and the 15:59 liquidation bar
  itself (17 touches) are excluded from the Stage 0 signal population by
  design (see `docs/STAGE0_EXCURSION_STUDY.md` section 2) -- they are not
  errors, but they do mean 4.5% of all physical touches never get a Stage 0
  path record.
- **`mfe`/`mae` are not floored at zero.** ~2% of signals have a negative
  MFE (never moved favourably) and ~2% have a positive MAE (never moved
  adversely) -- both are legitimate market outcomes, confirmed by
  `tests/test_signal_path_invariants.py::test_mfe_at_least_mae`, not
  computation errors. Any Stage 1 formula-fitting work should be aware most
  MAE/MFE-based quantile regressions implicitly assume this asymmetry.
- **Feature-scale stability ranking is descriptive, not a Stage 1
  pre-selection.** `outputs/stage0_feature_stability.csv` ranks scales by
  coefficient-of-variation of their annual normalized-MFE median only as an
  observational input for whoever designs Stage 1's preregistered scale
  list -- it is not itself a formula selection step.
