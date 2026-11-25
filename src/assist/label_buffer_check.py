"""35.104: how many labels does the 20 s buffer cost? closed_loop_fw with labeler.BUF unlimited (the MCU ring would
then have to hold the whole pick-and-place); compare lab_n with the committed BUF = 200 runs. Same seeds.
python src/assist/label_buffer_check.py <tag> <closed_loop_fw arguments>"""
import sys
sys.path.insert(0, '/work/src/assist')
sys.path.insert(0, '/work/src')
import labeler as LB  # noqa: E402
LB.BUF = 100000
LB.Labeler.__init__.__defaults__ = (LB.N_TAIL, 100000)   # buf is a default argument: override it there
assert LB.Labeler.__init__.__defaults__[1] == 100000
import closed_loop_fw as C  # noqa: E402
sys.argv = ['closed_loop_fw.py'] + sys.argv[2:] + ['--tag', sys.argv[1]]
C.main()
