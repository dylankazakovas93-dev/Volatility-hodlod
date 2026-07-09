# Leakage Audit — GC MAE/MFE Study

| check | passed |
|---|---|
| label horizon strictly after entry for every row | PASS |
| zero NaNs in final feature matrix (rows with any NaN were dropped, not imputed) | PASS |
| MAE/MFE magnitudes are all >= 0 | PASS |
| R-denominator (stop_distance_R_cap) strictly positive for every row (no div-by-zero) | PASS |
| trailing_5session_avg_ib_range_pts computed via rolling(5).shift(1) -- verified by construction, re-checked in tests/ | PASS |
| contract_id inherits the underlying continuous-series' same-day-volume roll rule (disclosed in docs/DATA_PIPELINE.md) -- flagged as CAVEAT in FEATURE_PROVENANCE.csv, not used in any fitted formula's feature set | PASS |

**Overall: ALL CHECKS PASS**

Feature set actually used in fitted formulas: ['sigma_day', 'vol_close_prior', 'ib_range_pts', 'level_distance_from_open_pts', 'side_direction', 'entry_hour_et', 'day_of_week', 'dist_prior_bar_close_pts', 'trailing_5session_avg_ib_range_pts', 'stop_distance_R_cap']

Every feature in this list was cross-referenced against `docs/gc_mae_mfe_study/FEATURE_PROVENANCE.csv` and carries status ALLOWED (contract_id, which is CAVEAT-flagged, was deliberately excluded from the fitted feature set for this reason). `year_time_index` (RESTRICTED) is used only for the stability breakdown in `CALIBRATION_REPORT.md`, never as a fitted predictor.
