"""Compare re-extracted features with a reference copy (e.g. the Windows features), file by file.

Expects the reference folders mounted at /ref/features_arm_position_windows and /ref/features_demo_windows:
  docker run --rm -v "$HOME/model":/work -v "$HOME/model_ref":/ref:ro -w /work rf-emg python src/compare_features.py
Prints the number of bit-identical files and the max abs / relative difference per feature.
"""
import glob, os, numpy as np
for name, base, ref in [("arm_position", "external/self-calibrating-rf/features_arm_position", "/ref/features_arm_position_windows"),
                        ("demo", "external/self-calibrating-rf/features_demo", "/ref/features_demo_windows")]:
    n = same = 0; worst_abs = worst_rel = 0.0; per = {}
    for f in sorted(glob.glob(base + "/*/*/*.npy")):
        a = np.load(f); b = np.load(os.path.join(ref, os.path.relpath(f, base)))
        d = np.abs(a - b); n += 1; same += int(np.array_equal(a, b))
        k = os.path.basename(f)[8:-4]
        per[k] = max(per.get(k, 0.0), float((d / np.maximum(np.abs(b), 1e-12)).max()))
        worst_abs = max(worst_abs, float(d.max())); worst_rel = max(worst_rel, float((d / np.maximum(np.abs(b), 1e-12)).max()))
    print(f"{name}: {same}/{n} files bit-identical, max abs diff {worst_abs:.3g}, max rel diff {worst_rel:.3g}")
    print("   max rel diff per feature:", {k: float(f"{v:.2g}") for k, v in sorted(per.items())})
