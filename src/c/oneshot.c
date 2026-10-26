/* One-shot calibration on the MCU: z-score, pruning (upstream emg_functions.prune), new trees, Flash image.
 * See oneshot.h.
 *
 * Pruning, equivalent to upstream prune() decision for decision:
 *   upstream walks the leaves that hold calibration samples from the deepest height up; for each leaf at height
 *   h it takes the parent P (depth h - 1), collects the true labels of all samples now in P's subtree, and
 *   turns P into a leaf labelled with their mode if that labels more of them correctly than the current
 *   leaves do (strictly). A leaf whose parent was already pruned is skipped, and a pruned P becomes a leaf at
 *   height h - 1 that is looked at in the next pass.
 *   Here: for h = deepest .. 1, every internal node P at depth h - 1 that is still internal and has a child that
 *   is a current leaf holding samples is evaluated once (P's at one depth have disjoint subtrees, so their
 *   order does not matter). statistics.mode returns the first most frequent value in data order; upstream's
 *   data order is the samples of the current leaves in node-id (pre-order) order, each leaf's samples in the
 *   order they reached it, which is: by pre-order of the original leaf, then by sample index. The samples are
 *   sorted once by that key. Traversal uses the MCU rule x < thr on the Q5.10 table.
 */
#include "oneshot.h"

#include <math.h>
#include <string.h>

#include "rf_train.h"
#if SC_EMBED
#include "tsne.h"
#endif

#if RFT_MAX_LEAVES < OS_MAX_LEAVES
#error "rf_train.h: RFT_MAX_LEAVES must be >= OS_MAX_LEAVES for one-shot trees"
#endif
#if RFT_NMAX < OS_CAL_MAX
#error "rf_train.h: RFT_NMAX too small for the calibration set"
#endif

#define ST_INTERNAL 0
#define ST_PRUNED 2
#define ST_BLOCKED 3                  /* below a pruned node: unreachable */

typedef struct {                      /* all working memory, placed in work_area() */
    float feat[OS_CAL_MAX][SC_DIM];   /* raw calibration features (filled by the caller) */
    int16_t q[OS_CAL_MAX][SC_DIM];
    const int16_t *rows[OS_CAL_MAX];
    uint8_t state[OS_TREE_INT_MAX], depth[OS_TREE_INT_MAX], plab[OS_TREE_INT_MAX];
    uint16_t path[OS_CAL_MAX][OS_MAX_DEPTH];
    uint16_t key[OS_CAL_MAX];
    uint8_t plen[OS_CAL_MAX], leafcls[OS_CAL_MAX], order[OS_CAL_MAX];
    os_header_t hdr;
    rft_tree_t tree;
    sc_node_t nodes[RFT_MAX_NODES];
    uint8_t bits[];                   /* prune bitmap, ceil(n_internal / 8) bytes */
} scratch_t;

#if SC_EMBED
#define work_area tsne_scratch                /* borrowed: one-shot runs before the first t-SNE */
#else
static uint64_t s_work[(OS_WORK_BYTES + 7) / 8];
static void *work_area(unsigned *bytes)
{
    *bytes = (unsigned)sizeof s_work;
    return s_work;
}
#endif

static scratch_t *scratch(uint32_t n_internal, uint32_t *need, uint32_t *have)
{
    unsigned bytes;
    void *p = work_area(&bytes);
    *need = (uint32_t)sizeof(scratch_t) + (n_internal + 7) / 8;
    *have = bytes;
    return *need <= bytes ? (scratch_t *)p : 0;
}

const int16_t *os_cal_rows(void)
{
    unsigned bytes;
    return &((scratch_t *)work_area(&bytes))->q[0][0];
}

float *os_feature_buffer(void)
{
    unsigned bytes;
    return &((scratch_t *)work_area(&bytes))->feat[0][0];
}

static uint32_t align(uint32_t x)
{
    return (x + OS_ALIGN - 1) & ~(OS_ALIGN - 1);
}

/* ---------------------------------------------------------------- pruning */
typedef int (*sink_fn)(void *ctx, const sc_prune_t *e);

static uint32_t tree_internal(const os_table_t *pre, int t)
{
    uint32_t end = pre->n_internal;
    for (int u = t + 1; u < SC_N_PRE; u++)
        if (!(pre->roots[u] & 0x80000000u)) {
            end = pre->roots[u];
            break;
        }
    return end - pre->roots[t];
}

static int prune_tree(const os_table_t *pre, int t, scratch_t *sc, const uint8_t *y, int n, sink_fn sink, void *ctx)
{
    const uint32_t root = pre->roots[t];
    if (root & 0x80000000u)
        return 0;                                         /* single leaf: nothing to prune */
    const uint32_t ni = tree_internal(pre, t);
    if (ni > OS_TREE_INT_MAX)
        return -1;
    const uint8_t *feat = pre->feat + root;
    const int16_t *thr = pre->thr + root;
    const uint16_t *L = pre->left + root, *R = pre->right + root;
    sc->depth[0] = 0;
    for (uint32_t i = 0; i < ni; i++) {                   /* table order is pre-order: parents first */
        sc->state[i] = ST_INTERNAL;
        if (!(L[i] & 0x8000u))
            sc->depth[L[i]] = (uint8_t)(sc->depth[i] + 1);
        if (!(R[i] & 0x8000u))
            sc->depth[R[i]] = (uint8_t)(sc->depth[i] + 1);
    }
    int hmax = 0;
    for (int s = 0; s < n; s++) {                         /* path of every calibration row */
        const int16_t *x = sc->rows[s];
        uint16_t node = 0, key = 0;
        int len = 0;
        for (;;) {
            if (len >= OS_MAX_DEPTH)
                return -1;
            sc->path[s][len] = node;
            int right = !(x[feat[node]] < thr[node]);
            key |= (uint16_t)(right << (OS_MAX_DEPTH - 1 - len));
            uint16_t c = right ? R[node] : L[node];
            len++;
            if (c & 0x8000u) {
                sc->leafcls[s] = (uint8_t)(c & 0x7fff);
                break;
            }
            node = c;
        }
        sc->plen[s] = (uint8_t)len;
        sc->key[s] = key;
        if (len > hmax)
            hmax = len;
        int p = s;                                        /* insertion sort by (leaf pre-order, index) */
        while (p > 0 && sc->key[sc->order[p - 1]] > key) {
            sc->order[p] = sc->order[p - 1];
            p--;
        }
        sc->order[p] = (uint8_t)s;
    }
    for (int h = hmax; h >= 1; h--) {
        for (uint32_t i = 0; i < ni; i++) {
            if (sc->depth[i] != h - 1 || sc->state[i] != ST_INTERNAL)
                continue;
            int cnt[SC_CLASSES] = {0}, first[SC_CLASSES], correct = 0, pos = 0, child_leaf = 0;
            for (int o = 0; o < n; o++) {
                int s = sc->order[o];
                if (sc->plen[s] < h || sc->path[s][h - 1] != i)
                    continue;
                int pred = sc->leafcls[s], at_child = (sc->plen[s] == h);
                for (int j = h; j < sc->plen[s]; j++)     /* current leaf: shallowest pruned node below P */
                    if (sc->state[sc->path[s][j]] == ST_PRUNED) {
                        pred = sc->plab[sc->path[s][j]];
                        at_child = (j == h);
                        break;
                    }
                child_leaf |= at_child;
                correct += (y[s] == pred);
                if (cnt[y[s]]++ == 0)
                    first[y[s]] = pos;
                pos++;
            }
            if (!child_leaf)
                continue;                                 /* no child leaf with samples: upstream never looks at P */
            int mode = -1;
            for (int c = 0; c < SC_CLASSES; c++)
                if (cnt[c] && (mode < 0 || cnt[c] > cnt[mode] || (cnt[c] == cnt[mode] && first[c] < first[mode])))
                    mode = c;
            if (cnt[mode] > correct) {                    /* strictly better on the calibration rows */
                sc->state[i] = ST_PRUNED;
                sc->plab[i] = (uint8_t)mode;
            }
        }
    }
    int emitted = 0;
    for (uint32_t i = 0; i < ni; i++) {                   /* reachable pruned nodes, in index order */
        if (sc->state[i] == ST_PRUNED || sc->state[i] == ST_BLOCKED) {
            if (!(L[i] & 0x8000u))
                sc->state[L[i]] = ST_BLOCKED;
            if (!(R[i] & 0x8000u))
                sc->state[R[i]] = ST_BLOCKED;
        }
        if (sc->state[i] == ST_PRUNED) {
            sc_prune_t e = {(uint16_t)(root + i), sc->plab[i], 0};
            if (sink(ctx, &e) != 0)
                return -4;
            emitted++;
        }
    }
    return emitted;
}

static int prune_all(const os_table_t *pre, scratch_t *sc, const uint8_t *y, int n, sink_fn sink, void *ctx)
{
    int total = 0;
    for (int t = 0; t < SC_N_PRE; t++) {
        int r = prune_tree(pre, t, sc, y, n, sink, ctx);
        if (r < 0)
            return r;
        total += r;
    }
    return total;
}

typedef struct {
    sc_prune_t *out;
    int max, n;
} array_sink_t;

static int to_array(void *ctx, const sc_prune_t *e)
{
    array_sink_t *a = ctx;
    if (a->n >= a->max)
        return -1;
    a->out[a->n++] = *e;
    return 0;
}

int os_prune(const os_table_t *pre, const int16_t *rows_q, const uint8_t *y, int n, sc_prune_t *out, int max_out)
{
    uint32_t need, have;
    scratch_t *sc = scratch(pre->n_internal, &need, &have);
    if (!sc)
        return -2;
    if (n < 1 || n > OS_CAL_MAX || pre->n_internal > OS_PRE_INT_MAX)
        return -1;
    for (int s = 0; s < n; s++)
        sc->rows[s] = rows_q + s * SC_DIM;
    array_sink_t a = {out, max_out, 0};
    int r = prune_all(pre, sc, y, n, to_array, &a);
    return r < 0 ? r : a.n;
}

/* ---------------------------------------------------------------- image */
typedef struct {
    const os_writer_t *w;
    uint32_t off;
    scratch_t *sc;
    uint32_t n;
} image_sink_t;

static int to_image(void *ctx, const sc_prune_t *e)
{
    image_sink_t *im = ctx;
    if (im->off + sizeof *e > im->w->capacity)
        return -1;
    if (im->w->write(im->w->ctx, im->off, e, sizeof *e) != 0)
        return -1;
    im->sc->bits[e->idx >> 3] |= (uint8_t)(1u << (e->idx & 7));
    im->off += sizeof *e;
    im->n++;
    return 0;
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

/* Seed of a tree's own xorshift32 stream. xorshift is linear: if tree seeds were consecutive outputs of this
 * stream, tree k+1 would replay tree k's draws shifted by one step (nearly the same bootstrap sample). A
 * splitmix32-style finaliser puts every tree at an unrelated point of the cycle. */
static uint32_t tree_seed(void)
{
    uint32_t x = rnd() + 0x9E3779B9u;
    x = (x ^ (x >> 16)) * 0x85EBCA6Bu;
    x = (x ^ (x >> 13)) * 0xC2B2AE35u;
    x ^= x >> 16;
    return x ? x : 1u;
}

/* rf_train output -> pre-order array of sc_node_t (children after parents); returns internal nodes, 0 = leaf */
static int serialise(const rft_tree_t *t, sc_node_t *o, uint8_t *leaf_class)
{
    if (t->left[0] < 0) {
        *leaf_class = t->cls[0];
        return 0;
    }
    int16_t idx[RFT_MAX_NODES], order[RFT_MAX_NODES], stack[RFT_MAX_NODES];
    int sp = 0, n = 0;
    stack[sp++] = 0;
    while (sp) {
        int v = stack[--sp];
        idx[v] = (int16_t)n;
        order[n++] = (int16_t)v;
        if (t->left[t->right[v]] >= 0)
            stack[sp++] = t->right[v];
        if (t->left[t->left[v]] >= 0)
            stack[sp++] = t->left[v];
    }
    for (int k = 0; k < n; k++) {
        int v = order[k], l = t->left[v], r = t->right[v];
        o[k].feat = t->feature[v];
        o[k].pad = 0;
        o[k].thr = t->thr[v];
        o[k].left = (t->left[l] < 0) ? (uint16_t)(0x8000u | t->cls[l]) : (uint16_t)idx[l];
        o[k].right = (t->left[r] < 0) ? (uint16_t)(0x8000u | t->cls[r]) : (uint16_t)idx[r];
    }
    return n;
}

static void quantize(const float *x, const float *mu, const float *inv_sd, int16_t *out)
{
    for (int f = 0; f < SC_DIM; f++) {
        float q = rintf((x[f] - mu[f]) * inv_sd[f] * 1024.0f);
        if (q > 32767.0f) q = 32767.0f;
        if (q < -32768.0f) q = -32768.0f;
        out[f] = (int16_t)q;
    }
}

void os_normalize(const os_header_t *h, const float *feat, int16_t *out)
{
    quantize(feat, h->mu, h->inv_sd, out);
}

int os_calibrate(const os_table_t *pre, const uint8_t *y, int n, uint32_t seed, const os_writer_t *w, int16_t *cal_q,
                 os_stats_t *st)
{
    memset(st, 0, sizeof *st);
    if (n < 2 || n > OS_CAL_MAX || pre->n_internal > OS_PRE_INT_MAX)
        return -1;
    uint32_t need, have;
    scratch_t *sc = scratch(pre->n_internal, &need, &have);
    st->scratch_bytes = need;
    if (!sc)
        return -2;
    os_header_t *h = &sc->hdr;
    memset(h, 0, sizeof *h);
    h->magic = OS_MAGIC;
    h->version = OS_VERSION;
    h->n_cal = (uint32_t)n;
    /* 1. z-score statistics (numpy mean / std, ddof 0) and Q5.10 rows */
    for (int f = 0; f < SC_DIM; f++) {
        double m = 0.0, v = 0.0;
        for (int s = 0; s < n; s++)
            m += sc->feat[s][f];
        m /= n;
        for (int s = 0; s < n; s++)
            v += (sc->feat[s][f] - m) * (sc->feat[s][f] - m);
        v = sqrt(v / n);
        h->mu[f] = (float)m;
        h->inv_sd[f] = v > 0.0 ? (float)(1.0 / v) : 0.0f;  /* constant feature: 0 (upstream would divide by 0) */
    }
    for (int s = 0; s < n; s++) {
        quantize(sc->feat[s], h->mu, h->inv_sd, sc->q[s]);
        sc->rows[s] = sc->q[s];
    }
    if (cal_q)
        memcpy(cal_q, sc->q, sizeof(int16_t) * SC_DIM * n);
    /* 2. prune the pre-trained trees, prune list streamed to the image */
    h->bits_bytes = (pre->n_internal + 7) / 8;
    memset(sc->bits, 0, h->bits_bytes);
    h->off_prune = align(sizeof *h);
    image_sink_t im = {w, h->off_prune, sc, 0};
    int r = prune_all(pre, sc, y, n, to_image, &im);
    if (r < 0)
        return r == -4 ? -4 : -1;
    h->n_prune = im.n;
    st->n_pruned_nodes = (int)im.n;
    /* 3. SC_N_APP new trees on the calibration rows, nodes streamed to the image */
    h->off_nodes = align(im.off);
    uint32_t off = h->off_nodes;
    s_rng = seed ? seed : 1u;
    for (int a = 0; a < SC_N_APP; a++) {
        if (rft_train(sc->rows, y, n, OS_MAX_DEPTH, OS_MAX_LEAVES, OS_MAX_FEATURES, tree_seed(), &sc->tree) != 0)
            return -1;
        uint8_t cls = 0;
        int k = serialise(&sc->tree, sc->nodes, &cls);
        int leaves = sc->tree.n_nodes - k;
        if (k == 0) {
            h->app_roots[a] = 0x80000000u | cls;
            leaves = 1;
        } else {
            h->app_roots[a] = h->n_nodes;
            uint32_t bytes = (uint32_t)k * sizeof(sc_node_t);
            if (off + bytes > w->capacity)
                return -4;
            if (w->write(w->ctx, off, sc->nodes, bytes) != 0)
                return -3;
            off += bytes;
            h->n_nodes += (uint32_t)k;
        }
        if (leaves > st->app_leaves_max)
            st->app_leaves_max = leaves;
    }
    st->app_nodes = (int)h->n_nodes;
    /* 4. bitmap, then the header (last: an image without a valid header is ignored) */
    h->off_bits = align(off);
    h->bytes = h->off_bits + h->bits_bytes;
    if (h->bytes > w->capacity)
        return -4;
    if (w->write(w->ctx, h->off_bits, sc->bits, h->bits_bytes) != 0 || w->write(w->ctx, 0, h, sizeof *h) != 0)
        return -3;
    st->image_bytes = h->bytes;
    return 0;
}

int os_model(const void *image, const os_table_t *pre, sc_model_t *m)
{
    const os_header_t *h = image;
    if (h->magic != OS_MAGIC || h->version != OS_VERSION)
        return -1;
    const uint8_t *base = image;
    m->roots = pre->roots;
    m->feat = pre->feat;
    m->thr = pre->thr;
    m->left = pre->left;
    m->right = pre->right;
    m->prune_bits = base + h->off_bits;
    m->prune = (const sc_prune_t *)(base + h->off_prune);
    m->n_prune = (int)h->n_prune;
    m->app_nodes = (const sc_node_t *)(base + h->off_nodes);
    m->app_roots = h->app_roots;
    return 0;
}
