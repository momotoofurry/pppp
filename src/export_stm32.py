"""Copy the bench firmware into a STM32CubeMX CMake project (NUCLEO-H753ZI) and make its linker script fit it.

Copies to <project>/emg/: the portable modules of firmware v2 (selfcal, kmeans, rf_train, features, adapt, oneshot
and their headers; tsne.h only for the declarations, SC_EMBED = 0 does not use it), board.h, board_hal.c (HAL board
layer), bench.c / bench.h, and the data headers made by build_arm_selfcal.py (build/oneshot_dev/pre_model.h,
cal_feat.h; build/bench/raw_bench.h from check_bench.py). Existing files in emg/ are overwritten; nothing else in the project
is touched except:
  <project>/<ld>_axi.ld   a copy of the CubeMX linker script with .data / .tdata / .tbss / .bss moved from the
                          128 KB DTCM to the 512 KB AXI SRAM (RAM), the stack and heap left in DTCM. The firmware
                          needs ~176 KB (results/arm_selfcal_size.csv, board2). The root CMakeLists.txt (generated
                          once by CubeMX, never regenerated) switches to it; see the printed lines.
Runs on the host, standard library only: python3 src/export_stm32.py /mnt/d/stm32/blink
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = os.path.join(ROOT, 'src', 'c')
SRC = ['selfcal', 'kmeans', 'rf_train', 'features', 'adapt', 'oneshot']
EXTRA = ['tsne.h', 'board.h', 'board_hal.c', 'bench.c', 'bench.h']
DATA = [os.path.join(ROOT, 'build', 'oneshot_dev', 'pre_model.h'), os.path.join(ROOT, 'build', 'oneshot_dev', 'cal_feat.h'),
        os.path.join(ROOT, 'build', 'bench', 'raw_bench.h')]


def axi_ld(text):
    """move the RAM sections of the CubeMX script from DTCMRAM to RAM (AXI SRAM); keep ._user_heap_stack"""
    out, n = [], 0
    section = None
    for line in text.splitlines(keepends=True):
        m = re.match(r'\s*(\.\w+)\s*(\(NOLOAD\))?\s*:', line)
        if m:
            section = m.group(1)
        if section in ('.data', '.tdata', '.tbss', '.bss') and re.search(r'}\s*>DTCMRAM', line):
            line = line.replace('>DTCMRAM', '>RAM')
            n += 1
        out.append(line)
    assert n == 4, f'expected 4 sections in DTCMRAM, moved {n}'
    return ''.join(out)


def main():
    proj = sys.argv[1]
    lds = [f for f in os.listdir(proj) if f.endswith('_FLASH.ld')]
    assert len(lds) == 1, lds
    dst = os.path.join(proj, 'emg')
    os.makedirs(dst, exist_ok=True)
    files = [f'{s}.{e}' for s in SRC for e in ('c', 'h')] + EXTRA
    for f in files:
        shutil.copy2(os.path.join(C, f), dst)
    for f in DATA:
        assert os.path.exists(f), f'{f} missing: run python src/build_arm_selfcal.py in the container first'
        shutil.copy2(f, dst)
    ld = lds[0]
    axi = ld[:-3] + '_axi.ld'
    with open(os.path.join(proj, ld)) as fh:
        text = fh.read()
    with open(os.path.join(proj, axi), 'w', newline='\n') as fh:
        fh.write(axi_ld(text))
    print(f'copied {len(files) + len(DATA)} files to {dst}; wrote {axi}')
    print('root CMakeLists.txt (once):')
    print('  target_sources(...): file(GLOB EMG_SRC ${CMAKE_SOURCE_DIR}/emg/*.c) and ${EMG_SRC}')
    print('  target_include_directories(...): ${CMAKE_SOURCE_DIR}/emg')
    print(f'  string(REPLACE "{ld}" "{axi}" CMAKE_EXE_LINKER_FLAGS "${{CMAKE_EXE_LINKER_FLAGS}}")  # after project()')


if __name__ == '__main__':
    main()
