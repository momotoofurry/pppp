/* CART training (best-first, gini, bootstrap), static memory only. See rf_train.h. */
#include "rf_train.h"

#include <float.h>
#include <string.h>

typedef struct {
    int16_t node;               /* node id */
    uint16_t start, end, pos;   /* row range in s_samples; pos = first right row */
    uint8_t depth, is_leaf, feature;
    int16_t thr;
    double improvement;
} record_t;

/* ---- static workspace (training RAM on the MCU) ---- */
static uint16_t s_samples[RFT_NMAX];     /* rows with bootstrap weight > 0, partitioned per node */
static uint16_t s_weight[RFT_NMAX];      /* bootstrap count per row */
static int16_t s_val[RFT_NMAX];          /* sort scratch: feature values ... */
static uint16_t s_idx[RFT_NMAX];         /* ... and their rows */
static record_t s_front[RFT_MAX_NODES];  /* best-first frontier */
static uint8_t s_feat[RFT_DIM];

unsigned rft_static_bytes(void)
{
    return (unsigned)(sizeof s_samples + sizeof s_weight + sizeof s_val + sizeof s_idx + sizeof s_front +
                      sizeof s_feat);
}

static uint32_t s_rng;
static uint32_t rnd(void)
{
    uint32_t x = s_rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return s_rng = x;
}

/* heapsort of (s_val, s_idx)[0..m) by value */
static void sift(int root, int m)
{
    for (;;) {
        int c = 2 * root + 1;
        if (c >= m)
            return;
        if (c + 1 < m && s_val[c + 1] > s_val[c])
            c++;
        if (s_val[root] >= s_val[c])
            return;
        int16_t v = s_val[root]; s_val[root] = s_val[c]; s_val[c] = v;
        uint16_t i = s_idx[root]; s_idx[root] = s_idx[c]; s_idx[c] = i;
        root = c;
    }
}

static void sort_pairs(int m)
{
    for (int r = m / 2 - 1; r >= 0; r--)
        sift(r, m);
    for (int e = m - 1; e > 0; e--) {
        int16_t v = s_val[0]; s_val[0] = s_val[e]; s_val[e] = v;
        uint16_t i = s_idx[0]; s_idx[0] = s_idx[e]; s_idx[e] = i;
        sift(0, e);
    }
}

static double gini(const uint32_t *cnt, double w)
{
    double s = 0.0;
    for (int c = 0; c < RFT_CLASSES; c++)
        s += (double)cnt[c] * cnt[c];
    return 1.0 - s / (w * w);
}

static const int16_t *const *g_rows;
static const uint8_t *g_y;
static double g_wtotal;

/* fills the node (value, class) and, unless it is a leaf, finds and applies its best split */
static void add_node(rft_tree_t *t, record_t *r, int max_depth, int max_features)
{
    uint32_t tot[RFT_CLASSES] = {0};
    for (int i = r->start; i < r->end; i++)
        tot[g_y[s_samples[i]]] += s_weight[s_samples[i]];
    double w = 0.0;
    int best_c = 0;
    for (int c = 0; c < RFT_CLASSES; c++) {
        w += tot[c];
        t->count[r->node][c] = (uint16_t)tot[c];
        if (tot[c] > tot[best_c])
            best_c = c;
    }
    t->cls[r->node] = (uint8_t)best_c;
    double imp = gini(tot, w);
    int n = r->end - r->start;
    r->is_leaf = 1;
    r->improvement = 0.0;
    if (r->depth >= max_depth || n < 2 || imp <= DBL_EPSILON)
        return;

    for (int f = 0; f < RFT_DIM; f++)
        s_feat[f] = (uint8_t)f;
    double best = -1.0;
    int best_f = -1, best_p = 0, visited = 0;
    int16_t best_thr = 0;
    uint32_t best_left[RFT_CLASSES];
    for (int k = 0; k < RFT_DIM && visited < max_features; k++) {
        int j = k + (int)(rnd() % (uint32_t)(RFT_DIM - k));   /* Fisher-Yates: random feature order */
        uint8_t f = s_feat[j];
        s_feat[j] = s_feat[k];
        s_feat[k] = f;
        for (int i = 0; i < n; i++) {
            s_idx[i] = s_samples[r->start + i];
            s_val[i] = g_rows[s_idx[i]][f];
        }
        sort_pairs(n);
        if (s_val[0] == s_val[n - 1])
            continue;                                         /* constant here: does not count */
        visited++;
        uint32_t left[RFT_CLASSES] = {0};
        double wl = 0.0;
        for (int p = 1; p < n; p++) {
            uint16_t row = s_idx[p - 1];
            left[g_y[row]] += s_weight[row];
            wl += s_weight[row];
            if (s_val[p] == s_val[p - 1])
                continue;
            double sl = 0.0, sr = 0.0;
            for (int c = 0; c < RFT_CLASSES; c++) {
                sl += (double)left[c] * left[c];
                sr += (double)(tot[c] - left[c]) * (tot[c] - left[c]);
            }
            double proxy = sl / wl + sr / (w - wl);
            if (proxy > best) {
                best = proxy;
                best_f = f;
                best_p = p;
                /* midpoint as sklearn, rounded up so that a < thr <= b: `x < thr` keeps the split exact */
                best_thr = (int16_t)(s_val[p - 1] + ((int32_t)s_val[p] - s_val[p - 1] + 1) / 2);
                memcpy(best_left, left, sizeof left);
            }
        }
    }
    if (best_f < 0)
        return;                                               /* every feature constant */
    (void)best_p;
    /* partition the node's rows: x < thr to the left */
    int lo = r->start, hi = r->end - 1;
    while (lo <= hi) {
        if (g_rows[s_samples[lo]][best_f] < best_thr)
            lo++;
        else {
            uint16_t tmp = s_samples[lo]; s_samples[lo] = s_samples[hi]; s_samples[hi] = tmp;
            hi--;
        }
    }
    double wl = 0.0;
    uint32_t right[RFT_CLASSES];
    for (int c = 0; c < RFT_CLASSES; c++) {
        wl += best_left[c];
        right[c] = tot[c] - best_left[c];
    }
    double wr = w - wl;
    r->pos = (uint16_t)lo;
    r->feature = (uint8_t)best_f;
    r->thr = best_thr;
    r->is_leaf = 0;
    r->improvement = (w / g_wtotal) * (imp - wr / w * gini(right, wr) - wl / w * gini(best_left, wl));
}

int rft_train(const int16_t *const *rows, const uint8_t *y, int n, int max_depth, int max_leaves,
              int max_features, uint32_t seed, rft_tree_t *t)
{
    if (n > RFT_NMAX || n < 1)
        return -1;
    if (max_leaves <= 0 || max_leaves > RFT_MAX_LEAVES)
        max_leaves = RFT_MAX_LEAVES;
    g_rows = rows;
    g_y = y;
    s_rng = seed ? seed : 0x9E3779B9u;
    memset(s_weight, 0, sizeof(uint16_t) * n);
    for (int i = 0; i < n; i++)                               /* bootstrap */
        s_weight[rnd() % (uint32_t)n]++;
    int m = 0;
    g_wtotal = 0.0;
    for (int i = 0; i < n; i++)
        if (s_weight[i]) {
            s_samples[m++] = (uint16_t)i;
            g_wtotal += s_weight[i];
        }

    t->n_nodes = 1;
    t->left[0] = t->right[0] = -1;
    int nf = 0;
    record_t *root = &s_front[nf++];
    root->node = 0;
    root->start = 0;
    root->end = (uint16_t)m;
    root->depth = 0;
    add_node(t, root, max_depth, max_features);
    int splits_left = max_leaves - 1;
    while (nf) {
        int b = 0;
        for (int i = 1; i < nf; i++)                          /* best-first: largest improvement */
            if (s_front[i].improvement > s_front[b].improvement)
                b = i;
        record_t r = s_front[b];
        s_front[b] = s_front[--nf];
        int id = r.node;
        if (r.is_leaf || splits_left <= 0) {
            t->left[id] = t->right[id] = -1;
            continue;
        }
        splits_left--;
        t->feature[id] = r.feature;
        t->thr[id] = r.thr;
        for (int side = 0; side < 2; side++) {
            int c = t->n_nodes++;
            t->left[c] = t->right[c] = -1;
            record_t *ch = &s_front[nf++];
            ch->node = (int16_t)c;
            ch->start = side ? r.pos : r.start;
            ch->end = side ? r.end : r.pos;
            ch->depth = (uint8_t)(r.depth + 1);
            add_node(t, ch, max_depth, max_features);
            if (side)
                t->right[id] = (int16_t)c;
            else
                t->left[id] = (int16_t)c;
        }
    }
    return 0;
}
