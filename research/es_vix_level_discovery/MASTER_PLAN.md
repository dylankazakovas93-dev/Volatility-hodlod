======================================================================
28. THIS SESSION: STAGE 0 ONLY
======================================================================

First save this complete specification verbatim as:

/workspaces/Volatility-hodlod/research/es_vix_level_discovery/MASTER_PLAN.md

For this session complete only:

1. Create branch:
   research/es-vix-level-mae-mfe-discovery

   from exact commit:
   f4a8bad0e9671a026280dba97c6df557a20e0684

2. Read all quant-stack safeguards.

3. Locate and validate the supplied ES data.

4. Obtain official VIX history only from Cboe, preferably:
   https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv

5. Create and validate the normalized VIX CSV.

6. Create or verify the causal ES continuous one-minute CSV.

7. Create:
   - HOLDOUT_LOCK.json
   - GRID_DEFINITION.json
   - TRIAL_REGISTRY.csv
   - data manifests
   - Stage 0 tests
   - PROGRESS.md

8. Register exactly 132 grid configurations before producing outcomes.

9. Create one Stage 0 evidence-lock commit and push normally.

Do not:

- run the level grid;
- calculate MAE/MFE results;
- rank configurations;
- eliminate candidates;
- inspect 2025–2026 outcomes;
- fit formulas;
- begin Gate A;
- modify the frozen NQ/VXN branch.

Stop after Stage 0 and report:

- branch and exact base commit;
- ES source files and coverage;
- ES continuous-file hash;
- official Cboe VIX raw and normalized hashes;
- locked holdout dates;
- registered grid count;
- test results;
- commit SHA;
- push result;
- confirmation that no performance outcomes were calculated;
- confirmation that 2025–2026 remains unopened.