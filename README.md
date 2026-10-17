# STM32H7 self-calibrating RF — PC baseline & model-size study

Upstream code/data: https://github.com/MoveR-Digital-Health-and-Care-Hub/self-calibrating-rf
(commit `48ea4d1fd22a525c88ffa5462b14dc7ccfa998ea`), cloned into `external/` (git-ignored, 1.7 GB).

## Setup (Windows, Git Bash)

```bash
git clone https://github.com/MoveR-Digital-Health-and-Care-Hub/self-calibrating-rf.git external/self-calibrating-rf
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r external/self-calibrating-rf/requirements.txt matplotlib pandas
```

## Stage 1 — reproduce PC baseline

```bash
.venv/Scripts/python -u src/run_upstream.py demo_feature_extract.py
.venv/Scripts/python -u src/run_upstream.py demo_replay.py --seed 0
.venv/Scripts/python -u src/run_upstream.py main_feature_extract_arm_position.py
.venv/Scripts/python -u src/run_upstream.py main_replay_arm_position.py --seed 0
.venv/Scripts/python src/make_baseline.py
.venv/Scripts/python src/compare_paper.py
```

`run_upstream.py` seeds numpy's global RNG (the upstream scripts set no seed) and redirects
the replay accuracies to `results/upstream/seed<N>/` (results here use seeds 0, 1, 2). `make_baseline.py` builds
`results/baseline.csv`, `results/baseline_by_position.csv`, `results/baseline_demo.csv`
and `results/baseline_blocks.png`.

## Stage 2 — model size and compression sweep

```bash
.venv/Scripts/python src/model_stats.py
.venv/Scripts/python src/pipeline.py
.venv/Scripts/python src/compression_sweep.py --seeds 0 1 2 3 4
.venv/Scripts/python src/compression_sweep.py --seeds 0 1 2 3 4 --n-app 200
.venv/Scripts/python src/plot_sweep.py
```

`pipeline.py` alone checks the vectorised predictor against upstream `get_predictions`.
The sweep needs the features from stage 1 and takes ~2.5 min per run on 20 cores.
Summary: `results/stage2_summary.md`.

## Stage 3 — C export, PC correctness check, Cortex-M7 build

```bash
.venv/Scripts/python -m pip install emlearn setuptools   # setuptools: emlearn imports distutils
.venv/Scripts/python src/export_c.py                     # -> build/<cfg>/ (git-ignored, regenerable)
.venv/Scripts/python src/check_c.py --cc "/c/Program Files/mingw64/bin/gcc.exe"
wsl -d Ubuntu-22.04 -- sudo apt-get install -y gcc-arm-none-eabi libnewlib-arm-none-eabi
.venv/Scripts/python src/build_arm.py --wsl              # arm-none-eabi-gcc 10.3.1 inside WSL2
```

## Stage 4 — report

```bash
.venv/Scripts/python src/ram_estimate.py   # design-level RAM estimate for on-MCU self-calibration
# self-calibration accuracy of compressed configs (~25 min + ~90 min on 20 cores)
.venv/Scripts/python src/selfcal_sweep.py --configs 0 --suffix _validation      # upstream model, float64
.venv/Scripts/python src/selfcal_sweep.py --configs 1 2 3 4 5 --suffix _compressed
.venv/Scripts/python src/selfcal_sweep.py --merge _validation _compressed       # -> selfcal_sweep*.csv
```
Report: `report.md`.
