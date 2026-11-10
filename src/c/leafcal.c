/* Leaf counters, static memory only. See leafcal.h. */
#include "leafcal.h"

#include <string.h>

static lc_model_t s_m;
static uint8_t s_cnt[LC_MAX_LEAVES][LC_CLASSES];

unsigned lc_static_bytes(void)
{
    return (unsigned)(sizeof s_m + sizeof s_cnt);
}

void lc_reset(void)
{
    memset(s_cnt, 0, sizeof s_cnt);
}

int lc_init(const lc_model_t *m)
{
    if (m->leaf_base[LC_N_TREES] > LC_MAX_LEAVES)
        return -1;
    s_m = *m;
    lc_reset();
    return 0;
}

/* leaf of tree t for x: returns the child code (leaf index << 3 | class) */
static uint16_t leaf(int t, const int16_t *x)
{
    const uint32_t root = s_m.roots[t];
    if (root & 0x80000000u)
        return (uint16_t)(root & 7u);           /* single leaf: index 0 */
    const uint8_t *feat = s_m.feat + root;
    const int16_t *thr = s_m.thr + root;
    const uint16_t *l = s_m.left + root, *r = s_m.right + root;
    uint16_t n = 0;
    for (;;) {
        uint16_t c = (x[feat[n]] < thr[n]) ? l[n] : r[n];
        if (c & 0x8000u)
            return c & 0x7fffu;
        n = c;
    }
}

void lc_learn(const int16_t *x, int label)
{
    if (label < 0 || label >= LC_CLASSES)
        return;
    for (int t = 0; t < LC_N_TREES; t++) {
        if (s_m.leaf_base[t] == s_m.leaf_base[t + 1])
            continue;                           /* tree without counters */
        uint8_t *c = s_cnt[s_m.leaf_base[t] + (leaf(t, x) >> 3)];
        if (++c[label] == 255)
            for (int k = 0; k < LC_CLASSES; k++)
                c[k] >>= 1;
    }
}

int lc_votes(const int16_t *x, uint16_t *v)
{
    memset(v, 0, sizeof(uint16_t) * LC_CLASSES);
    for (int t = 0; t < LC_N_TREES; t++) {
        const uint16_t code = leaf(t, x);
        int best = code & 7;                    /* one-shot class of the leaf */
        if (s_m.leaf_base[t] != s_m.leaf_base[t + 1]) {
            const uint8_t *c = s_cnt[s_m.leaf_base[t] + (code >> 3)];
            const int base = best;
            int top = -1;
            for (int k = 0; k < LC_CLASSES; k++) {
                const int s = 2 * c[k] + (k == base);
                if (s > top) {
                    top = s;
                    best = k;
                }
            }
        }
        v[best]++;
    }
    int b = 0;
    for (int k = 1; k < LC_CLASSES; k++)
        if (v[k] > v[b])
            b = k;
    return b;
}

int lc_predict(const int16_t *x)
{
    uint16_t v[LC_CLASSES];
    return lc_votes(x, v);
}
