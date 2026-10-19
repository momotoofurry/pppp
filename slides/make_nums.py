"""Pull every number the slide builders use out of results/ into slides/nums*.json.

  nums.json   build.py   (v2: reproduction, compression, RAM scenarios A-C)
  nums2.json  build3.py  (v3: pseudo-label methods, per-method RAM)
  nums3.json  build5.py  (int16 buffer, buffer size, 32-leaf trees)
  nums4.json  build5.py  (nums3 + small buffer x 32 leaves, t-SNE cost)
  nums5.json  build7.py  (nums4 + t-SNE iteration count)
  nums6.json  build8.py  (nums5 + C implementations, Cortex-M7 self-calibration build, demo)
Usage (repo root, in the Docker image): python slides/make_nums.py
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'results')
OUT = os.path.dirname(os.path.abspath(__file__))


def csv(name, **kw):
    return pd.read_csv(os.path.join(R, name), **kw)


def dump(name, obj):
    with open(os.path.join(OUT, name), 'w', encoding='utf8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print('wrote', name)


# ---------------------------------------------------------------- nums.json (build.py)
b = csv('baseline.csv')
per = b.groupby(['method', 'subject', 'block']).accuracy.mean().reset_index()
blk = (per.groupby(['method', 'block']).accuracy.mean() * 100).unstack()
subj = per.groupby(['method', 'subject']).accuracy.mean().unstack(0) * 100
r = csv('ram_estimate.csv').set_index('item').bytes
g = csv('ram_estimate.csv').groupby('group').bytes.sum()
common = (r['feature buffers + stack (d10_n100_i16, table)'] + g['feature extraction'] + r['buffer pseudo-labels']
          + r['RF training scratch (one tree at a time)'])
tr_i16 = r['replaceable trees, 50 appended, depth 10 int16 (largest run)']
tr_f32 = r['replaceable trees, 200 appended, no depth limit float32 (largest run)']
tsne = g['pseudo-label: Barnes-Hut t-SNE 3-D']
km = g['pseudo-label: K-Means 80-D']
sc = {'A': common + g['self-cal buffer (float32)'] + tr_f32 + tsne + km,
      'B': common + g['self-cal buffer (int16)'] + tr_i16 + tsne + km,
      'C': common + g['self-cal buffer (int16)'] + tr_i16 + km,
      'D': common + g['self-cal buffer (float32)'] + tr_f32,
      'E': common + g['self-cal buffer (int16)'] + tr_i16}
s = csv('selfcal_sweep_summary.csv')
a = csv('arm_size.csv')
dump('nums.json', {
    'blocks': {m: [round(v, 2) for v in blk.loc[m].values] for m in blk.index},
    'all': {m: round(subj[m].mean(), 2) for m in subj},
    'sd_selfcal': round(subj['self-calibrating RF'].std(), 2),
    'n_better': int((subj['self-calibrating RF'] > subj['fixed: one-shot RF']).sum()),
    'ram_KB': {k: round(v / 1024, 1) for k, v in sc.items()},
    'tsne_KB': round(tsne / 1024, 1),
    'selfcal': s[['config', 'acc_oneshot', 'acc_selfcal', 'gain']].round(2).values.tolist(),
    'arm': a[['config', 'impl', 'flash_KB', 'static_ram_bytes', 'worst_stack_bytes']].round(1).values.tolist()})

# ---------------------------------------------------------------- nums2.json (build3.py)
pl = csv('pseudo_label_summary.csv')
ram = csv('ram_scenarios_pseudo.csv')
n2 = {'pseudo': {}, 'ram': {}}
cols = ['acc_oneshot', 'acc_selfcal', 'selfcal_seed_min', 'selfcal_seed_max', 'gain', 'paper_ablation',
        'diff_vs_tsne', 'n_subjects_better', 'wilcoxon_p', 'app_nodes_max']
for _, row in pl.iterrows():
    k = ('full' if str(row.config).startswith('400') else 'c3') + '_' + row.pseudo_label
    n2['pseudo'][k] = {c: (None if pd.isna(row[c]) else float(row[c])) for c in cols}
for _, row in ram.iterrows():
    n2['ram'][('full' if row.model.startswith('400') else 'c3') + '_' + row.pseudo_label] = float(row.total_KB)
dump('nums2.json', n2)

# ---------------------------------------------------------------- nums3.json / nums4.json (build5.py)
lb = csv('leaf_buffer_summary.csv').set_index('config')


def f(c, k):
    return float(lb.loc[c, k])


n3 = {'tsne': [dict(n=n, acc=f(c, 'acc_selfcal'), gain=f(c, 'gain'), ram=f(c, 'total_KB'), p=f(c, 'wilcoxon_p'),
                    diff=f(c, 'diff_vs_baseline'))
               for c, n in [('N100_d10_int16_bq16', 1500), ('N100_d10_int16_buf1000_bq16', 1000),
                            ('N100_d10_int16_buf750_bq16', 750), ('N100_d10_int16_buf500_bq16', 500)]],
      'leaf32': dict(acc=f('N100_d10_int16_mln32', 'acc_selfcal'), bound=f('N100_d10_int16_mln32', 'trees_bound_KB'),
                     p=f('N100_d10_int16_mln32', 'wilcoxon_p')),
      'base': dict(acc=f('N100_d10_int16', 'acc_selfcal'), gain=f('N100_d10_int16', 'gain')),
      'nocluster': dict(acc=n2['pseudo']['c3_none']['acc_selfcal'], gain=n2['pseudo']['c3_none']['gain'], ram=n2['ram']['c3_none']),
      'kmeans': dict(acc=n2['pseudo']['c3_kmeans']['acc_selfcal'], gain=n2['pseudo']['c3_kmeans']['gain'], ram=n2['ram']['c3_kmeans'])}
dump('nums3.json', n3)
n4 = dict(n3)
n4['combo'] = [dict(n=n, acc=f(c, 'acc_selfcal'), gain=f(c, 'gain'), ram=f(c, 'total_KB'), p=f(c, 'wilcoxon_p'),
                    better=int(f(c, 'n_subjects_better')))
               for c, n in [('N100_d10_int16_mln32_buf750_bq16', 750), ('N100_d10_int16_mln32_buf500_bq16', 500),
                            ('N100_d10_int16_mln32_buf375_bq16', 375), ('N100_d10_int16_mln32_buf250_bq16', 250)]]
tc = csv('tsne_cost.csv')
n4['tsne_cost'] = [dict(buffer=int(buf), n=float(g_.n_tsne.mean()), iters=float(g_.n_iter.mean()),
                        cpu=float(g_.cpu_s.mean()), subjects=int(len(g_)))
                   for buf, g_ in tc.groupby('buffer', sort=False)]
dump('nums4.json', n4)

# ---------------------------------------------------------------- nums5.json (build7.py)
ti = csv('tsne_iter_summary.csv')
n5 = dict(n4)
n5['tsne_iter'] = [dict(it=int(r_.tsne_iter), acc=float(r_.acc_selfcal), gain=float(r_.gain), diff=float(r_.diff_vs_1000),
                        p=float(r_.wilcoxon_p), worse=int(r_.n_subjects_worse), cpu=float(r_.tsne_cpu_s),
                        rel=float(r_.tsne_cpu_rel_1000), subjects=int(r_.cost_subjects))
                   for _, r_ in ti.iterrows()]
dump('nums5.json', n5)

# ---------------------------------------------------------------- nums6.json (build8.py)
ci = csv('c_impl_summary.csv')
sz = csv('arm_selfcal_size.csv')
md = csv('arm_selfcal_modules.csv')
n6 = dict(n5)
n6['c_impl'] = [dict(variant=r_.variant, acc=float(r_.acc_selfcal), gain=float(r_.gain),
                     diff=None if pd.isna(r_.diff_vs_sklearn) else float(r_.diff_vs_sklearn),
                     p=None if pd.isna(r_.wilcoxon_p) else float(r_.wilcoxon_p),
                     better=None if pd.isna(r_.n_better) else int(r_.n_better),
                     worse=None if pd.isna(r_.n_worse) else int(r_.n_worse)) for _, r_ in ci.iterrows()]
tc = csv('tsne_c_check.csv')
n6['tsne_c_time'] = {str(it): dict(c=float(g_.cpu_c_s.mean()), sk=float(g_.cpu_sklearn_s.mean()))
                     for it, g_ in tc.groupby('max_iter')}
fcc = csv('features_c_check.csv')
n6['feat_mismatch'] = {f: int(round(((1 - g_.exact) * g_.n).sum())) for f, g_ in fcc.groupby('feature')}
n6['feat_values'] = int(fcc[fcc.feature == 'rms'].n.sum())
sf, sr = csv('selfcal_sweep_fc.csv'), csv('selfcal_sweep_iter.csv')
sr = sr[sr.tsne_iter == 500].merge(sf, on=['seed', 'subject', 'block'], suffixes=('', '_c'))
n6['feat_oneshot_same_blocks'] = [int((sr.acc_oneshot == sr.acc_oneshot_c).sum()), int(len(sr))]
os_ = md[md.opt == '-Os']
n6['arm'] = {}
for v, g_ in os_.groupby('variant'):
    row = sz[(sz.variant == v) & (sz.opt == '-Os')].iloc[0]
    bss = {m_.split('.')[0]: int(b_) for m_, b_ in zip(g_.module, g_.bss)}
    sym = dict(x.split('=') for x in row.largest_ram_symbols.split(';'))
    n6['arm'][v] = dict(text=int(row.text), data=int(row.data), bss=int(row.bss), stack=int(row.worst_stack_bytes),
                        flash_KB=float(row.flash_KB), bss_modules=bss, buf=int(sym['s_buf']), cal=int(sym['s_cal']),
                        trees=int(sym['s_tree']),
                        total_KB=(int(row.bss) + int(row.data) + int(row.worst_stack_bytes)) / 1024)
if os.path.exists(os.path.join(R, 'c_impl_demo.csv')):
    n6['demo'] = [dict(variant=r_.variant, oneshot=float(r_.acc_oneshot), acc=float(r_.acc_selfcal), gain=float(r_.gain),
                       lo=float(r_.selfcal_seed_min), hi=float(r_.selfcal_seed_max),
                       tail_os=float(r_.oneshot_blocks7_9), tail_sc=float(r_.selfcal_blocks7_9))
                  for _, r_ in csv('c_impl_demo.csv').iterrows()]
dump('nums6.json', n6)
# per-block demo curves (build8.py, 前置結果⑩)
if os.path.exists(os.path.join(R, 'c_impl_demo.csv')):
    ref_ = csv('selfcal_sweep_demo_ref.csv')
    curves = {'full': ref_[ref_.config == 'N400_dnone_float64'], 'mcu_c': csv('selfcal_c_check_demo.csv')}
    n6['demo_blocks'] = {k: dict(oneshot=[float(v) for v in d.groupby('block').acc_oneshot.mean() * 100],
                                 selfcal=[float(v) for v in d.groupby('block').acc_selfcal.mean() * 100],
                                 seeds=int(d.seed.nunique()))
                         for k, d in curves.items()}
    dump('nums6.json', n6)
