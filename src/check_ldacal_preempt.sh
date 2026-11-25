#!/bin/bash
# report 35.103: readers (the classifier) running in the middle of ld_fit must see a whole model, and a failed fit
# must leave the model in use untouched. Compiles src/c/ldacal.c with test hooks (LD_TEST_HOOK) on the PC.
#   bash src/check_ldacal_preempt.sh        (needs gcc; ALL OK expected)
set -e
cd "$(dirname "$0")/c"
W=$(mktemp -d)
echo 'void hook(int point);' > $W/hook.h
gcc -O2 -Wall -Wextra -DLD_CLASSES=9 -DLD_TEST_HOOK=hook -include $W/hook.h ldacal.c ldacal_preempt_test.c -lm -o $W/t
$W/t
rm -rf $W
