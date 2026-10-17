#!/usr/bin/env bash
# Runs inside the container (via docker/run.sh). Same steps as README.md.
#   setup    clone the upstream repo (code + data, 1.7 GB) into external/ if it is missing
#   verify   quick cross-platform check against the committed results (~5 min)
#   stage1   feature extraction + upstream replays (3 seeds in parallel, ~1.5 h) + tables
#   stage2   model stats + compression sweeps + plot (~5 min)
#   stage3   C export, PC check (gcc), Cortex-M7 build (arm-none-eabi-gcc) (~3 min)
#   selfcal  self-calibration accuracy of compressed configs (~2 h)
#   all      stage1 .. selfcal in order
set -euo pipefail
cd /work
UPSTREAM_URL=https://github.com/MoveR-Digital-Health-and-Care-Hub/self-calibrating-rf.git
UPSTREAM_COMMIT=48ea4d1fd22a525c88ffa5462b14dc7ccfa998ea
REPO=external/self-calibrating-rf
mkdir -p results/logs

setup() {
    if [[ ! -d $REPO/.git ]]; then
        git clone "$UPSTREAM_URL" "$REPO"
    fi
    git -c safe.directory='*' -C "$REPO" -c advice.detachedHead=false checkout -q "$UPSTREAM_COMMIT"
    echo "upstream at $(git -c safe.directory='*' -C "$REPO" rev-parse HEAD)"
}

need_features() {
    if [[ ! -d $REPO/features_arm_position ]]; then
        echo "missing $REPO/features_arm_position: run 'stage1' (or 'features')" >&2
        exit 1
    fi
}

features() {
    setup
    python -u src/run_upstream.py demo_feature_extract.py > results/logs/demo_feature_extract.log 2>&1
    python -u src/run_upstream.py main_feature_extract_arm_position.py > results/logs/arm_feature_extract.log 2>&1
}

verify() {
    need_features
    python -u src/verify_platform.py "$@"
}

stage1() {
    features
    for s in 0 1 2; do
        python -u src/run_upstream.py demo_replay.py --seed $s > results/logs/demo_replay_seed$s.log 2>&1 &
    done
    wait
    for s in 0 1 2; do
        python -u src/run_upstream.py main_replay_arm_position.py --seed $s > results/logs/arm_replay_seed$s.log 2>&1 &
    done
    wait
    python src/make_baseline.py
    python src/compare_paper.py
}

stage2() {
    need_features
    python src/model_stats.py
    python src/pipeline.py
    python src/compression_sweep.py --seeds 0 1 2 3 4 > results/logs/compression_sweep.log 2>&1
    python src/compression_sweep.py --seeds 0 1 2 3 4 --n-app 200 > results/logs/compression_sweep_app200.log 2>&1
    python src/plot_sweep.py
}

stage3() {
    need_features
    python src/export_c.py
    python src/check_c.py --cc gcc 2>&1 | tee results/logs/check_c.log
    python src/build_arm.py 2>&1 | tee results/logs/build_arm.log   # native toolchain: no --wsl
}

selfcal() {
    need_features
    python -u src/selfcal_sweep.py --configs 0 --suffix _validation > results/logs/selfcal_validation.log 2>&1
    python -u src/selfcal_sweep.py --configs 1 2 3 4 5 --suffix _compressed > results/logs/selfcal_compressed.log 2>&1
    python src/selfcal_sweep.py --merge _validation _compressed
    python src/ram_estimate.py
}

step=${1:-verify}
shift || true
case "$step" in
    setup|features|verify|stage1|stage2|stage3|selfcal) "$step" "$@" ;;
    all) stage1; stage2; stage3; selfcal ;;
    *) echo "unknown step: $step" >&2; exit 2 ;;
esac
