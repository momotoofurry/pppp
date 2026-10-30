/* On-device self-calibration, static memory only. See selfcal.h. */
#include "selfcal.h"

#include <math.h>
#include <string.h>

#include "kmeans.h"
#include "rf_train.h"
#if SC_EMBED
#include "tsne.h"
#if TSNE_NMAX < SC_BUF
#error "tsne.h: TSNE_NMAX too small for the self-calibration buffer"
#endif
#endif

#if KM_NMAX < SC_BUF || RFT_NMAX < SC_BUF + SC_CAL_MAX || RFT_MAX_LEAVES < SC_MAX_LEAVES || KM_QDIM != SC_DIM
#error "module sizes too small for the self-calibration buffer"
#endif

#define NODES (SC_MAX_LEAVES - 1)               /* internal nodes of a RAM tree */
#if defined(__arm__)
#define SC_BARRIER() __asm volatile("dmb" ::: "memory")
#else
#define SC_BARRIER() __asm volatile("" ::: "memory")
#endif

typedef struct {                                /* RAM tree, same encoding as rf_predict.h */
    uint8_t n;                                  /* internal nodes; 0 -> single leaf, class in left[0] */
    uint8_t feat[NODES];
    int16_t thr[NODES];
    uint16_t left[NODES], right[NODES];         /* bit 15 set -> leaf (low bits = class) */
} ram_tree_t;

/* ---- state ---- */
static sc_model_t s_m;
static int16_t s_buf[SC_BUF][SC_DIM];           /* buffer rows (unordered); order kept in s_key */
static uint8_t s_lab[SC_BUF];
static int32_t s_key[SC_BUF];                   /* list position: smaller = nearer the front */
static int s_n;
static int32_t s_front;                         /* key of the current front row */
static int16_t s_cal[SC_CAL_MAX][SC_DIM];
static uint8_t s_cal_y[SC_CAL_MAX];
static int s_ncal;
static ram_tree_t s_tree[SC_N_APP];
static volatile uint8_t s_ram[SC_N_APP];        /* slot uses s_tree (1) or the one-shot tree (0) */
static uint32_t s_rng;
/* ---- work ---- */
static const int16_t *s_rows[SC_BUF + SC_CAL_MAX];
static uint8_t s_y[SC_BUF + SC_CAL_MAX];
static uint16_t s_sel[SC_BUF];
#if SC_EMBED
static float s_emb[SC_BUF * 3];
#endif
static uint8_t s_km[SC_BUF];
static rft_tree_t s_new;
static int32_t s_block_base;                    /* keys reserved for the rows concatenated in this block */
static int s_block_rows, s_in_block;

unsigned sc_static_bytes(void)
{
    return (unsigned)(sizeof s_m + sizeof s_buf + sizeof s_lab + sizeof s_key + sizeof s_cal + sizeof s_cal_y +
                      sizeof s_tree + sizeof s_ram + sizeof s_rows + sizeof s_y + sizeof s_sel +
#if SC_EMBED
                      sizeof s_emb +
#endif
                      sizeof s_km + sizeof s_new);
}

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

#if SC_EMBED
static float gauss(void)                        /* Box-Muller */
{
    float u1 = ((rnd() >> 8) + 1.0f) / 16777217.0f, u2 = (rnd() >> 8) / 16777216.0f;
    return sqrtf(-2.0f * logf(u1)) * cosf(6.2831853f * u2);
}
#endif

/* ---------------------------------------------------------------- inference */
static int pruned_label(uint32_t g)             /* binary search in the sorted prune list */
{
    int lo = 0, hi = s_m.n_prune - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        if (s_m.prune[mid].idx == g)
            return s_m.prune[mid].label;
        if (s_m.prune[mid].idx < g)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return 0;                                   /* not reached: every set bit has an entry */
}

static int flash_tree(int t, const int16_t *x)
{
    if (t >= SC_N_PRE && s_m.app_nodes) {       /* one-shot calibration tree from the Flash image */
        const uint32_t root = s_m.app_roots[t - SC_N_PRE];
        if (root & 0x80000000u)
            return (int)(root & 0xffu);
        const sc_node_t *nd = s_m.app_nodes + root;
        uint16_t n = 0;
        for (;;) {
            uint16_t c = (x[nd[n].feat] < nd[n].thr) ? nd[n].left : nd[n].right;
            if (c & 0x8000u)
                return c & 0x7fff;
            n = c;
        }
    }
    const uint32_t root = s_m.roots[t];
    if (root & 0x80000000u)
        return (int)(root & 0xffu);
    const uint8_t *feat = s_m.feat + root;
    const int16_t *thr = s_m.thr + root;
    const uint16_t *l = s_m.left + root, *r = s_m.right + root;
    const uint8_t *bits = (t < SC_N_PRE) ? s_m.prune_bits : 0;
    uint16_t n = 0;
    for (;;) {
        if (bits && (bits[(root + n) >> 3] >> ((root + n) & 7)) & 1u)
            return pruned_label(root + n);      /* pruned during one-shot calibration */
        uint16_t c = (x[feat[n]] < thr[n]) ? l[n] : r[n];
        if (c & 0x8000u)
            return c & 0x7fff;
        n = c;
    }
}

static int ram_tree(const ram_tree_t *t, const int16_t *x)
{
    if (t->n == 0)
        return t->left[0] & 0x7fff;
    uint16_t n = 0;
    for (;;) {
        uint16_t c = (x[t->feat[n]] < t->thr[n]) ? t->left[n] : t->right[n];
        if (c & 0x8000u)
            return c & 0x7fff;
        n = c;
    }
}

static int vote(const uint16_t *v)
{
    int b = 0;
    for (int k = 1; k < SC_CLASSES; k++)
        if (v[k] > v[b])
            b = k;
    return b;
}

static int votes_sc(const int16_t *x, uint16_t *v)
{
    memset(v, 0, sizeof(uint16_t) * SC_CLASSES);
    for (int t = 0; t < SC_N_PRE; t++)
        v[flash_tree(t, x)]++;
    for (int s = 0; s < SC_N_APP; s++)
        v[s_ram[s] ? ram_tree(&s_tree[s], x) : flash_tree(SC_N_PRE + s, x)]++;
    return vote(v);
}

int sc_votes(const int16_t *x, uint16_t *votes)
{
    return votes_sc(x, votes);
}

int sc_predict(const int16_t *x)
{
    uint16_t v[SC_CLASSES];
    return votes_sc(x, v);
}

#if SC_ROLLBACK
/* candidate rollback rule (report 22, PC only): keep the previous trees, check the updated model on the stored
 * calibration rows, restore if it got worse */
static ram_tree_t s_tree_bak[SC_N_APP];
static uint8_t s_ram_bak[SC_N_APP];

void sc_save(void)
{
    memcpy(s_tree_bak, s_tree, sizeof s_tree);
    for (int s = 0; s < SC_N_APP; s++)
        s_ram_bak[s] = s_ram[s];
}

void sc_restore(void)
{
    memcpy(s_tree, s_tree_bak, sizeof s_tree);
    for (int s = 0; s < SC_N_APP; s++)
        s_ram[s] = s_ram_bak[s];
}

void sc_skip_block(void)
{
    s_in_block = 0;                             /* the block's rows stay in the buffer; no pseudo-labels, no trees */
}

int sc_cal_correct(void)
{
    int ok = 0;
    for (int i = 0; i < s_ncal; i++)
        ok += sc_predict(s_cal[i]) == s_cal_y[i];
    return ok;
}
#endif

int sc_votes_oneshot(const int16_t *x, uint16_t *v)
{
    memset(v, 0, sizeof(uint16_t) * SC_CLASSES);
    for (int t = 0; t < SC_N_PRE + SC_N_APP; t++)
        v[flash_tree(t, x)]++;
    return vote(v);
}

int sc_predict_oneshot(const int16_t *x)
{
    uint16_t v[SC_CLASSES];
    return sc_votes_oneshot(x, v);
}

void sc_init(const sc_model_t *m, const int16_t *cal, const uint8_t *cal_y, int n_cal, uint32_t seed)
{
    s_m = *m;
    s_ncal = n_cal < SC_CAL_MAX ? n_cal : SC_CAL_MAX;
    memcpy(s_cal, cal, sizeof(int16_t) * SC_DIM * s_ncal);
    memcpy(s_cal_y, cal_y, s_ncal);
    for (int k = 0; k < SC_N_APP; k++)
        s_ram[k] = 0;
    s_n = 0;
    s_front = 0;
    s_in_block = 0;
    s_rng = seed ? seed : 1u;
}

/* ---------------------------------------------------------------- buffer (upstream buffer_update)
 * Upstream, per block: while the buffer has room the block's rows are concatenated in front (row 0 first);
 * once it is full each further row is inserted at the front and evicts the last row of the most frequent
 * label. Rows are stored unordered; s_key keeps the list order (smaller = nearer the front). Concatenated
 * rows get keys block_base + j from a range reserved below the old front, rows inserted one by one get
 * keys below block_base, so the order is the upstream order without holding the block in RAM. */
static void buffer_push(const int16_t *x, uint8_t lab)
{
    int slot;
    int32_t key;
    if (s_n < SC_BUF) {
        slot = s_n++;
        key = s_block_base + s_block_rows;
    } else {
        int cnt[SC_CLASSES] = {0};
        for (int j = 0; j < s_n; j++)
            cnt[s_lab[j]]++;
        int most = 0;
        for (int k = 1; k < SC_CLASSES; k++)
            if (cnt[k] > cnt[most])
                most = k;
        slot = -1;
        for (int j = 0; j < s_n; j++)
            if (s_lab[j] == most && (slot < 0 || s_key[j] > s_key[slot]))
                slot = j;
        key = --s_front;
    }
    memcpy(s_buf[slot], x, sizeof s_buf[slot]);
    s_lab[slot] = lab;
    s_key[slot] = key;
    s_block_rows++;
}

int sc_push(const int16_t *x)
{
    uint16_t v[SC_CLASSES];
    return sc_push_votes(x, v);
}

int sc_push_votes(const int16_t *x, uint16_t *votes)
{
    if (!s_in_block) {
        s_in_block = 1;
        s_block_rows = 0;
        s_block_base = s_front - SC_BLOCK_MAX;
        s_front = s_block_base;
    }
    int lab = votes_sc(x, votes);             /* the model does not change within a block */
    buffer_push(x, (uint8_t)lab);
    return lab;
}

void sc_rescale(const float *scale, const float *offset, int with_cal)
{
    for (int j = 0; j < s_n + (with_cal ? s_ncal : 0); j++) {
        int16_t *r = j < s_n ? s_buf[j] : s_cal[j - s_n];
        for (int d = 0; d < SC_DIM; d++) {
            float v = rintf((float)r[d] * scale[d] + offset[d]);
            r[d] = (int16_t)(v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : v);
        }
    }
}

/* first `m` rows (front first) of class c -> s_sel[at..] */
static int take_class(int c, int m, int at)
{
    int got = 0;
    int32_t after = INT32_MIN;
    while (got < m) {                           /* selection by key, m small */
        int best = -1;
        for (int j = 0; j < s_n; j++)
            if (s_lab[j] == c && s_key[j] > after && (best < 0 || s_key[j] < s_key[best]))
                best = j;
        if (best < 0)
            break;
        s_sel[at + got++] = (uint16_t)best;
        after = s_key[best];
    }
    return got;
}

static void store_tree(const rft_tree_t *t, ram_tree_t *o)
{
    if (t->left[0] < 0) {                       /* single leaf */
        o->n = 0;
        o->left[0] = 0x8000u | t->cls[0];
        return;
    }
    int16_t idx[RFT_MAX_NODES];                 /* internal nodes in pre-order (children after parents) */
    int16_t order[RFT_MAX_NODES], stack[RFT_MAX_NODES];
    int sp = 0, n = 0;
    stack[sp++] = 0;
    while (sp) {
        int v = stack[--sp];
        idx[v] = (int16_t)n;
        order[n++] = (int16_t)v;
        if (t->right[v] >= 0 && t->left[t->right[v]] >= 0)
            stack[sp++] = t->right[v];
        if (t->left[v] >= 0 && t->left[t->left[v]] >= 0)
            stack[sp++] = t->left[v];
    }
    o->n = (uint8_t)n;
    for (int k = 0; k < n; k++) {
        int v = order[k], l = t->left[v], r = t->right[v];
        o->feat[k] = t->feature[v];
        o->thr[k] = t->thr[v];
        o->left[k] = (t->left[l] < 0) ? (uint16_t)(0x8000u | t->cls[l]) : (uint16_t)idx[l];
        o->right[k] = (t->left[r] < 0) ? (uint16_t)(0x8000u | t->cls[r]) : (uint16_t)idx[r];
    }
}

/* ---------------------------------------------------------------- one self-calibration step */
void sc_end_block(sc_stats_t *st)
{
    memset(st, 0, sizeof *st);
    s_in_block = 0;
    /* 2. re-label the buffer with the one-shot model */
    int cnt[SC_CLASSES] = {0};
    for (int j = 0; j < s_n; j++) {
        s_lab[j] = (uint8_t)sc_predict_oneshot(s_buf[j]);
        cnt[s_lab[j]]++;
    }
    /* 3. class-balanced selection, pseudo-labels */
    int mn = s_n + 1, mn_nz = s_n + 1;
    for (int k = 0; k < SC_CLASSES; k++) {
        if (cnt[k] < mn) mn = cnt[k];
        if (cnt[k] > 0 && cnt[k] < mn_nz) mn_nz = cnt[k];
    }
    int ns = 0;
    int m = (mn < SC_MIN_CLASS) ? mn_nz : mn;
    for (int k = 0; k < SC_CLASSES; k++)
        if (cnt[k] > 0)
            ns += take_class(k, m, ns);
    for (int i = 0; i < ns; i++) {
        s_rows[i] = s_buf[s_sel[i]];
        s_y[i] = s_lab[s_sel[i]];
    }
    st->buffer_n = s_n;
    st->n_selected = ns;
#if !SC_EMBED
    if (mn >= SC_MIN_CLASS) {                   /* K-Means on the rows, initialised at the class centres */
        static float ctr[SC_CLASSES * SC_DIM];
        group_centres_q(s_rows, ns, s_y, SC_CLASSES, ctr);
        if (km_fit_q(s_rows, ns, SC_CLASSES, ctr, 300, 1e-4f, s_km) >= 0) {
            int seen[SC_CLASSES] = {0}, all = 1;
            for (int i = 0; i < ns; i++)
                seen[s_km[i]] = 1;
            for (int k = 0; k < SC_CLASSES; k++)
                all &= seen[k];
            if (all)
                memcpy(s_y, s_km, ns);
            st->clustered = 1;
        }
    }
#else
    if (mn >= SC_MIN_CLASS) {
        tsne_stats_t ts;
        for (int i = 0; i < 3 * ns; i++)
            s_emb[i] = 1e-4f * gauss();
        if (tsne_run(s_rows, ns, SC_PERPLEXITY, SC_TSNE_ITER, s_emb, s_emb, &ts) == 0) {
            float ctr[SC_CLASSES * 3];
            standardize(s_emb, ns);
            group_centres(s_emb, ns, s_y, SC_CLASSES, ctr);
            if (km_fit(s_emb, ns, SC_CLASSES, ctr, 300, 1e-4f, s_km) >= 0) {
                int seen[SC_CLASSES] = {0}, all = 1;
                for (int i = 0; i < ns; i++)
                    seen[s_km[i]] = 1;
                for (int k = 0; k < SC_CLASSES; k++)
                    all &= seen[k];
                if (all)
                    memcpy(s_y, s_km, ns);
                st->clustered = 1;
            }
            st->tsne_cells_max = ts.cells_max;
        }
    }
#endif
    /* 4. train SC_N_UPD trees on pseudo-labelled rows + calibration set, replace random slots */
    int nt = ns;
    for (int i = 0; i < s_ncal; i++) {
        s_rows[nt] = s_cal[i];
        s_y[nt++] = s_cal_y[i];
    }
    uint8_t perm[SC_N_APP];
    for (int s = 0; s < SC_N_APP; s++)
        perm[s] = (uint8_t)s;
    for (int s = SC_N_APP - 1; s > 0; s--) {
        int j = (int)(rnd() % (uint32_t)(s + 1));
        uint8_t t = perm[s]; perm[s] = perm[j]; perm[j] = t;
    }
    uint8_t replace[SC_N_APP] = {0};
    for (int s = SC_N_APP - SC_N_UPD; s < SC_N_APP; s++)
        replace[perm[s]] = 1;
    for (int s = 0; s < SC_N_APP; s++) {        /* new trees go to the replaced slots in slot order */
        if (!replace[s])
            continue;
        rft_train(s_rows, s_y, nt, SC_MAX_DEPTH, SC_MAX_LEAVES, 8, tree_seed(), &s_new);
        /* inference may run in an interrupt while this runs: the slot falls back to its one-shot (Flash) tree
         * while its RAM tree is rewritten, so a half-written tree is never traversed */
        s_ram[s] = 0;
        SC_BARRIER();
        store_tree(&s_new, &s_tree[s]);
        SC_BARRIER();
        s_ram[s] = 1;
        if (s_tree[s].n > st->new_nodes_max)
            st->new_nodes_max = s_tree[s].n;
    }
    for (int s = 0; s < SC_N_APP; s++)
        st->ram_trees += s_ram[s];
}
