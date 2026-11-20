#!/bin/sh
# Build and run the float32 accumulation check (report 35.73). Run from the repo root (WSL).
# Generated from src/c/ldacal.c / .h by sed, never edited by hand:
#   ldacal_ref.*  float -> double everywhere, prefix lr_  (reference)
#   ldacal_mix.*  only the running sums s_g, s_sum, s_n and G - s s^T / n in double, prefix lm_  (candidate fix)
set -e
B=build/precision
mkdir -p "$B" results
sed -e 's/\bld_/lr_/g' -e 's/\bfloat\b/double/g' -e 's/ldacal\.h/ldacal_ref.h/' \
    -e 's/sqrtf/sqrt/g' -e 's/expf/exp/g' -e 's/\([0-9]\)f\b/\1/g' src/c/ldacal.c > "$B/ldacal_ref.c"
sed -e 's/\bld_/lr_/g' -e 's/\bfloat\b/double/g' -e 's/\([0-9]\)f\b/\1/g' \
    -e '/#define LD_/d' -e '/#ifndef LD_CLASSES/,/#endif/d' src/c/ldacal.h > "$B/ldacal_ref.h"
sed -i '1i #include "ldacal.h"' "$B/ldacal_ref.h"
sed -e 's/\bld_/lm_/g' -e 's/ldacal\.h/ldacal_mix.h/' \
    -e 's/^static float s_g\[/static double s_g[/' -e 's/^static float s_sum\[/static double s_sum[/' \
    -e 's/^static float s_n\[/static double s_n[/' -e 's/float v = s_g\[TRI(i, j)\];/double v = s_g[TRI(i, j)];/' \
    -e 's/float n_all = 0.0f;/double n_all = 0.0;/' -e 's/const float inv_n = 1.0f \/ n_all;/const double inv_n = 1.0 \/ n_all;/' \
    -e 's/float \*g = s_g;/double *g = s_g;/' \
    src/c/ldacal.c > "$B/ldacal_mix.c"
grep -q 'static double s_g\[' "$B/ldacal_mix.c" && grep -q 'double v = s_g' "$B/ldacal_mix.c"
test "$(grep -c 'double \*g = s_g;' "$B/ldacal_mix.c")" = 2      # ld_add and ld_add_soft
# compile warnings are errors here: a float * pointing at the double sums would silently corrupt them
gcc -c -O2 -Werror=incompatible-pointer-types -DLD_CLASSES=9 -iquote src/c -iquote "$B" -o /dev/null "$B/ldacal_mix.c"
sed -e 's/\bld_/lm_/g' -e '/#define LD_/d' -e '/#ifndef LD_CLASSES/,/#endif/d' src/c/ldacal.h > "$B/ldacal_mix.h"
sed -i '1i #include "ldacal.h"' "$B/ldacal_mix.h"
# -iquote, not -I: src/c/features.h would shadow the system <features.h>
# -ffp-contract=off: no fused multiply-add on the PC (the board's GCC fuses some; 35.14 saw score differences of
# at most 0.13 log-odds from that, separate from the accumulation question here)
gcc -O2 -ffp-contract=off -DLD_CLASSES=9 -iquote src/c -iquote "$B" -o "$B/ldacal_precision" \
    src/c/ldacal_precision.c src/c/ldacal.c "$B/ldacal_ref.c" "$B/ldacal_mix.c" -lm
OUT=results/ldacal_precision.csv
echo "case,seed,day,windows,acc32,acc64,accmix,agree32,agreemix,score_err32,score_errmix,rho32,rho64,fit32,fit64,fitmix" > "$OUT"
for seed in 1 2 3; do
  #     name        days task OFF K   SEP  DUP
  for c in "dup_hard   730 1500 0 0  0.12 1" \
           "dup_heavy  365 6000 0 0  0.12 1" \
           "dup_off2   730 1500 2 0  0.12 1" \
           "dup_decay  365 1500 0 15 0.12 1" \
           "nodup_hard 730 1500 0 0  0.12 0" \
           "dup_easy   730 1500 0 0  0.35 1"; do
    set -- $c
    "$B/ldacal_precision" "$2" "$3" "$4" "$5" "$seed" "$6" "$7" | sed "s/^/$1,$seed,/" >> "$OUT"
  done
done
echo "wrote $OUT"
