#!/bin/bash
# 35.96: the post-recording analysis chain on the dry-run files (as on next week's T00_d1_S / T00_d2_S)
cd /work
D=/sp/dry96
O=/out
mkdir -p $O
echo "== 1. data quality (selftest_quality.py)"
python src/selftest_quality.py --dir $D --name Z99_d1_S --out $O 2>&1 | tail -25
echo "== 2. frozen decision P1 / P2 (selftest_s7_prereg.py)"
python src/selftest_s7_prereg.py --dir $D --days Z99_d1_S --out $O 2>&1 | tail -30
echo "== 3. offline analysis (selftest9_analysis.py --sets S7)"
python src/selftest9_analysis.py --dir $D --days Z99_d1_S --sets S7 --out $O 2>&1 | tail -30
echo "== outputs"; ls -la $O
echo ANALYZE_DONE
