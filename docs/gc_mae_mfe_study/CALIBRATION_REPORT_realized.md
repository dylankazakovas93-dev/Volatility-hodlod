**Label definition: A (realized in-position, censored by the strategy's own exit rules)**

# Calibration Report — GC MAE/MFE Formulas
All numbers below are computed on the **validation** split (2025) unless a section says test (2026-partial); test is touched exactly once, at the end, per the no-tuning rule.

## MAE_R

### validation (linear regression), n=160
- mean abs error: 0.4100 R
- RMSE: 0.4757 R
- median abs error: 0.4061 R
- bias (mean residual, actual-predicted): -0.1020 R

**Quantile coverage (validation, MAE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.5 | 0.594 |
| 0.75 | 0.831 |
| 0.9 | 0.794 |
| 0.95 | 0.863 |

**Worst overpredictions (validation, MAE_R, linear model, top 3):**

- 2025-11-26 06:32:00-05:00: actual=0.179R predicted=1.231R resid=-1.052R side=upper
- 2025-11-28 09:40:00-05:00: actual=0.044R predicted=0.997R resid=-0.953R side=upper
- 2025-03-13 08:06:00-04:00: actual=0.001R predicted=0.918R resid=-0.917R side=upper

**Worst underpredictions (validation, MAE_R, linear model, top 3):**

- 2025-11-14 07:12:00-05:00: actual=1.041R predicted=0.176R resid=0.865R side=lower
- 2025-10-21 20:06:00-04:00: actual=0.644R predicted=-0.152R resid=0.796R side=lower
- 2025-10-28 01:35:00-04:00: actual=1.050R predicted=0.312R resid=0.738R side=lower

### test (linear regression), n=61
- mean abs error: 0.6730 R
- RMSE: 1.0560 R
- median abs error: 0.3129 R
- bias (mean residual, actual-predicted): 0.3800 R

**Quantile coverage (test, MAE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.5 | 0.590 |
| 0.75 | 0.738 |
| 0.9 | 0.492 |
| 0.95 | 0.541 |

**Worst overpredictions (test, MAE_R, linear model, top 3):**

- 2026-04-28 01:45:00-04:00: actual=0.019R predicted=1.283R resid=-1.264R side=lower
- 2026-04-24 00:25:00-04:00: actual=0.113R predicted=1.286R resid=-1.173R side=lower
- 2026-04-28 01:06:00-04:00: actual=0.298R predicted=1.278R resid=-0.980R side=lower

**Worst underpredictions (test, MAE_R, linear model, top 3):**

- 2026-02-01 20:09:00-05:00: actual=0.364R predicted=-3.430R resid=3.794R side=lower
- 2026-02-02 00:52:00-05:00: actual=0.651R predicted=-2.484R resid=3.135R side=lower
- 2026-01-30 04:51:00-05:00: actual=0.042R predicted=-2.999R resid=3.041R side=lower

## MFE_R

### validation (linear regression), n=160
- mean abs error: 0.3739 R
- RMSE: 0.4636 R
- median abs error: 0.3128 R
- bias (mean residual, actual-predicted): 0.0221 R

**Quantile coverage (validation, MFE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.25 | 0.250 |
| 0.5 | 0.537 |
| 0.75 | 0.800 |
| 0.9 | 0.887 |

**Worst overpredictions (validation, MFE_R, linear model, top 3):**

- 2025-01-28 19:00:00-05:00: actual=0.067R predicted=1.523R resid=-1.457R side=upper
- 2025-11-24 19:00:00-05:00: actual=0.667R predicted=1.675R resid=-1.008R side=upper
- 2025-05-14 08:36:00-04:00: actual=0.229R predicted=1.012R resid=-0.783R side=lower

**Worst underpredictions (validation, MFE_R, linear model, top 3):**

- 2025-12-22 20:10:00-05:00: actual=1.746R predicted=0.420R resid=1.327R side=upper
- 2025-04-03 07:41:00-04:00: actual=1.016R predicted=-0.079R resid=1.095R side=lower
- 2025-01-15 08:30:00-05:00: actual=2.069R predicted=1.028R resid=1.041R side=upper

### test (linear regression), n=61
- mean abs error: 0.6516 R
- RMSE: 1.0127 R
- median abs error: 0.3920 R
- bias (mean residual, actual-predicted): 0.1713 R

**Quantile coverage (test, MFE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.25 | 0.230 |
| 0.5 | 0.557 |
| 0.75 | 0.754 |
| 0.9 | 0.918 |

**Worst overpredictions (test, MFE_R, linear model, top 3):**

- 2026-03-18 07:40:00-04:00: actual=0.037R predicted=1.775R resid=-1.738R side=lower
- 2026-02-03 01:26:00-05:00: actual=0.139R predicted=1.776R resid=-1.637R side=upper
- 2026-03-26 01:56:00-04:00: actual=0.286R predicted=1.730R resid=-1.445R side=lower

**Worst underpredictions (test, MFE_R, linear model, top 3):**

- 2026-01-30 04:51:00-05:00: actual=1.011R predicted=-2.671R resid=3.682R side=lower
- 2026-02-02 00:52:00-05:00: actual=1.067R predicted=-2.397R resid=3.464R side=lower
- 2026-02-01 20:09:00-05:00: actual=0.599R predicted=-2.037R resid=2.636R side=lower

## Stability breakdowns (validation split only)

### MAE_R — by year

| year | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| 2025 | 160 | 0.512 | 0.614 |

### MAE_R — long vs short

| side | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| lower | 53 | 0.516 | 0.523 |
| upper | 107 | 0.510 | 0.659 |

### MAE_R — volatility-regime tercile (sigma_day, train-fit boundaries)

| tercile | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| mid | 2 | 0.173 | 0.803 |
| high | 158 | 0.516 | 0.612 |

### MAE_R — time-of-day bucket

| bucket | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| pre-11:00 | 109 | 0.531 | 0.647 |
| 15:00-24:00 | 51 | 0.472 | 0.542 |

### MFE_R — by year

| year | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| 2025 | 160 | 0.623 | 0.601 |

### MFE_R — long vs short

| side | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| lower | 53 | 0.654 | 0.599 |
| upper | 107 | 0.608 | 0.602 |

### MFE_R — volatility-regime tercile (sigma_day, train-fit boundaries)

| tercile | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| mid | 2 | 0.399 | 0.763 |
| high | 158 | 0.626 | 0.599 |

### MFE_R — time-of-day bucket

| bucket | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| pre-11:00 | 109 | 0.602 | 0.569 |
| 15:00-24:00 | 51 | 0.669 | 0.669 |
