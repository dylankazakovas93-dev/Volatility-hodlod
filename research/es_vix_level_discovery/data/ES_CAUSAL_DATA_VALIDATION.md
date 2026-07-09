# ES Causal Continuous Data Validation

## Primary file

`data/es_1m/es_continuous_causal_2018_2026_1m.csv` (gitignored)

Built by `scripts/build_es_continuous_causal.py` using prior-session volume dominance.

## Properties

| Property | Value |
|---|---|
| SHA-256 | `646529f6e81729b84fcf3ae49c17ca1b64ebc869fcca0ff9ab9c1c9accbab897` |
| Row count | 2,804,976 |
| First timestamp | 2018-01-02 05:00:00+00:00 |
| Last timestamp | 2026-06-08 23:59:00+00:00 |
| First complete RTH session | 2018-01-02 |
| Last complete RTH session | 2026-06-08 |
| Contracts used | 34 |
| Roll days | 33 |
| Duplicate timestamps | 0 |
| Null values | 0 |
| OHLC consistency | All rows: low ≤ open,close ≤ high |
| Builder script SHA-256 | `8191781447480ab41f71c15063a4b154f3e6366b7f52356658622eba285bad5c` |

## Source archives

| Archive | SHA-256 |
|---|---|
| `es2018.zip` | `0498cc64e762f727c677f4ceadb6ed739a04276c80b4ad83a2055a03d04012e7` |
| `es2023.zip` | `993561800f6755a61d96bb9698bf7547a315fb1c74ae450b7c7fc7270e8ca31f` |
| `es2026.zip` | `91ed2c5a3f5518467701b6cf2967ef8729aa6ed25bea0a6a8aacd3e6a742bf15` |

## Regeneration command

```
python3 scripts/build_es_continuous_causal.py \
    --zip /workspaces/quant-stack/data/raw/ES/es2018.zip \
    --zip /workspaces/quant-stack/data/raw/ES/es2023.zip \
    --zip /workspaces/quant-stack/data/raw/ES/es2026.zip \
    --out data/es_1m/es_continuous_causal_2018_2026_1m.csv
```

## Causal roll schedule

See `ES_CAUSAL_ROLL_SCHEDULE.csv` for all 33 rolls with timestamps.

## Contract-selection rule

For ES RTH session D, the active contract is the standard quarterly ES contract
(`ES[HMUZ]\d`) with the highest total RTH (09:30-16:00 ET) volume during the
most recent prior RTH session with available data. If the immediate prior
weekday (e.g., Good Friday) has no RTH data, the algorithm walks back up to 30
days until a session with volume data is found. If no prior data exists at all,
the earliest-expiry contract available on that session is used.

This is **purely causal**: session D's volume never influences session D's
contract choice.