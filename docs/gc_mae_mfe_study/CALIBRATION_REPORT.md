# Calibration Report — GC MAE/MFE Formulas
All numbers below are computed on the **validation** split (2025) unless a section says test (2026-partial); test is touched exactly once, at the end, per the no-tuning rule.

## MAE_R

### validation (linear regression), n=350
- mean abs error: 1.1431 R
- RMSE: 1.4714 R
- median abs error: 0.9445 R
- bias (mean residual, actual-predicted): -0.0154 R

**Quantile coverage (validation, MAE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.5 | 0.514 |
| 0.75 | 0.826 |
| 0.9 | 0.911 |
| 0.95 | 0.909 |

**Worst overpredictions (validation, MAE_R, linear model, top 3):**

- 2025-11-24 19:00:00-05:00: actual=0.534R predicted=5.979R resid=-5.445R side=upper
- 2025-09-17 14:01:00-04:00: actual=0.458R predicted=5.040R resid=-4.583R side=lower
- 2025-01-28 19:00:00-05:00: actual=2.101R predicted=5.696R resid=-3.595R side=upper

**Worst underpredictions (validation, MAE_R, linear model, top 3):**

- 2025-12-12 11:02:00-05:00: actual=0.225R predicted=-4.520R resid=4.745R side=lower
- 2025-12-29 09:02:00-05:00: actual=1.155R predicted=-3.132R resid=4.288R side=lower
- 2025-03-12 22:52:00-04:00: actual=6.113R predicted=1.989R resid=4.124R side=upper

### test (linear regression), n=129
- mean abs error: 2.1723 R
- RMSE: 3.2142 R
- median abs error: 1.2223 R
- bias (mean residual, actual-predicted): 1.5887 R

**Quantile coverage (test, MAE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.5 | 0.550 |
| 0.75 | 0.729 |
| 0.9 | 0.752 |
| 0.95 | 0.721 |

**Worst overpredictions (test, MAE_R, linear model, top 3):**

- 2026-01-29 10:27:00-05:00: actual=0.807R predicted=5.989R resid=-5.183R side=lower
- 2026-04-14 21:16:00-04:00: actual=0.187R predicted=3.918R resid=-3.731R side=upper
- 2026-02-12 11:14:00-05:00: actual=1.276R predicted=3.463R resid=-2.187R side=lower

**Worst underpredictions (test, MAE_R, linear model, top 3):**

- 2026-02-02 11:01:00-05:00: actual=0.021R predicted=-9.693R resid=9.713R side=lower
- 2026-01-30 04:51:00-05:00: actual=1.353R predicted=-8.301R resid=9.655R side=lower
- 2026-01-30 12:07:00-05:00: actual=1.419R predicted=-7.360R resid=8.779R side=lower

## MFE_R

### validation (linear regression), n=350
- mean abs error: 1.3116 R
- RMSE: 1.7751 R
- median abs error: 1.1164 R
- bias (mean residual, actual-predicted): -0.4879 R

**Quantile coverage (validation, MFE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.25 | 0.314 |
| 0.5 | 0.549 |
| 0.75 | 0.783 |
| 0.9 | 0.877 |

**Worst overpredictions (validation, MFE_R, linear model, top 3):**

- 2025-10-27 04:53:00-04:00: actual=0.424R predicted=5.214R resid=-4.790R side=lower
- 2025-11-24 19:00:00-05:00: actual=1.327R predicted=5.296R resid=-3.969R side=upper
- 2025-04-28 14:24:00-04:00: actual=0.323R predicted=4.029R resid=-3.706R side=upper

**Worst underpredictions (validation, MFE_R, linear model, top 3):**

- 2025-02-13 20:02:00-05:00: actual=16.468R predicted=2.355R resid=14.113R side=upper
- 2025-08-19 19:52:00-04:00: actual=10.629R predicted=2.966R resid=7.663R side=lower
- 2025-03-19 20:04:00-04:00: actual=7.620R predicted=2.162R resid=5.457R side=upper

### test (linear regression), n=129
- mean abs error: 2.8697 R
- RMSE: 3.7832 R
- median abs error: 2.0740 R
- bias (mean residual, actual-predicted): -1.2350 R

**Quantile coverage (test, MFE_R):**

| target quantile | predicted-quantile coverage (actual) |
|---|---|
| 0.25 | 0.225 |
| 0.5 | 0.512 |
| 0.75 | 0.829 |
| 0.9 | 0.891 |

**Worst overpredictions (test, MFE_R, linear model, top 3):**

- 2026-02-09 10:33:00-05:00: actual=0.119R predicted=7.772R resid=-7.653R side=upper
- 2026-02-03 01:26:00-05:00: actual=0.139R predicted=7.565R resid=-7.426R side=upper
- 2026-03-26 01:56:00-04:00: actual=1.324R predicted=8.313R resid=-6.988R side=lower

**Worst underpredictions (test, MFE_R, linear model, top 3):**

- 2026-02-02 01:38:00-05:00: actual=2.020R predicted=-9.285R resid=11.305R side=lower
- 2026-01-30 13:20:00-05:00: actual=1.070R predicted=-9.262R resid=10.332R side=lower
- 2026-01-30 04:51:00-05:00: actual=1.023R predicted=-8.198R resid=9.220R side=lower

## Stability breakdowns (validation split only)

### MAE_R — by year

| year | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| 2025 | 350 | 1.162 | 1.178 |

### MAE_R — long vs short

| side | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| lower | 125 | 0.775 | 0.777 |
| upper | 225 | 1.378 | 1.400 |

### MAE_R — volatility-regime tercile (sigma_day, train-fit boundaries)

| tercile | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| mid | 2 | 3.462 | 1.248 |
| high | 348 | 1.149 | 1.177 |

### MAE_R — time-of-day bucket

| bucket | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| pre-11:00 | 207 | 1.141 | 1.079 |
| 11:00-15:00(blocked pop.) | 56 | 0.344 | 0.688 |
| 15:00-24:00 | 87 | 1.740 | 1.727 |

### MFE_R — by year

| year | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| 2025 | 350 | 1.136 | 1.624 |

### MFE_R — long vs short

| side | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| lower | 125 | 1.253 | 1.505 |
| upper | 225 | 1.072 | 1.690 |

### MFE_R — volatility-regime tercile (sigma_day, train-fit boundaries)

| tercile | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| mid | 2 | 2.773 | 1.597 |
| high | 348 | 1.127 | 1.624 |

### MFE_R — time-of-day bucket

| bucket | n | mean actual | mean predicted (linear) |
|---|---|---|---|
| pre-11:00 | 207 | 1.054 | 1.565 |
| 11:00-15:00(blocked pop.) | 56 | 0.502 | 1.015 |
| 15:00-24:00 | 87 | 1.741 | 2.157 |
