/* Barnes-Hut t-SNE (3-D), static memory only. See tsne.h for what is mirrored from scikit-learn. */
#include "tsne.h"

#include <math.h>
#include <string.h>

#define D3 3
#define DOF 2.0f                    /* sklearn: max(n_components - 1, 1) */
#define EXAG 12.0f
#define EXPLORE_ITER 250
#define CHECK_EVERY 50
#define MIN_GAIN 0.01f
#define MIN_GRAD_NORM 1e-7
#define THETA2 0.25f                /* angle 0.5, squared */
#define DUP_EPS 1e-6f               /* sklearn quad tree EPSILON */
#define MAX_DEPTH 48
#define PERP_STEPS 100
#define PERP_TOL 1e-5

typedef struct {
    float bary[D3];                 /* barycentre of the points below */
    uint16_t size;                  /* number of points below (duplicates included) */
    uint8_t depth;
    uint8_t leaf;
    int16_t child[8];               /* -1: none */
    uint16_t point;                 /* leaf: index of its point */
} cell_t;

/* ---- static workspace (this is the t-SNE RAM on the MCU) ---- */
static uint16_t s_nbr[TSNE_NMAX * TSNE_K];   /* directed kNN edges */
static float s_p[TSNE_NMAX * TSNE_K];        /* symmetrised, normalised P per edge (half of p_ij) */
static float s_upd[TSNE_NMAX * D3];
static float s_gain[TSNE_NMAX * D3];
static float s_grad[TSNE_NMAX * D3];
static cell_t s_cell[TSNE_CELLS];
static int16_t s_stack[8 * MAX_DEPTH + 8];   /* octree traversal */

unsigned tsne_static_bytes(void)
{
    return (unsigned)(sizeof s_nbr + sizeof s_p + sizeof s_upd + sizeof s_gain + sizeof s_grad + sizeof s_cell +
                      sizeof s_stack);
}

/* ---------------------------------------------------------------- P: kNN + perplexity search */
static void joint_probabilities(const int16_t *x, int n, int k, float perplexity)
{
    const double desired = log((double)perplexity);
    double sum_all = 0.0;
    for (int i = 0; i < n; i++) {
        float dk[TSNE_K];               /* k smallest squared distances, ascending */
        uint16_t ik[TSNE_K];
        int m = 0;
        const int16_t *xi = x + (long)i * TSNE_DIM;
        for (int j = 0; j < n; j++) {
            if (j == i)
                continue;
            const int16_t *xj = x + (long)j * TSNE_DIM;
            int64_t acc = 0;
            for (int f = 0; f < TSNE_DIM; f++) {
                int32_t d = (int32_t)xi[f] - xj[f];
                acc += (int64_t)d * d;
            }
            float d2 = (float)((double)acc * (1.0 / (1 << 20)));   /* Q5.10 squared -> real units */
            if (m == k && d2 >= dk[k - 1])
                continue;
            int p = (m < k) ? m++ : k - 1;
            while (p > 0 && dk[p - 1] > d2) {
                dk[p] = dk[p - 1];
                ik[p] = ik[p - 1];
                p--;
            }
            dk[p] = d2;
            ik[p] = (uint16_t)j;
        }
        /* binary search on beta (sklearn _binary_search_perplexity, using neighbours) */
        double P[TSNE_K], beta = 1.0, bmin = -INFINITY, bmax = INFINITY;
        for (int step = 0; step < PERP_STEPS; step++) {
            double sum = 0.0, sdp = 0.0;
            for (int j = 0; j < k; j++) {
                P[j] = exp(-(double)dk[j] * beta);
                sum += P[j];
            }
            if (sum == 0.0)
                sum = 1e-8;
            for (int j = 0; j < k; j++) {
                P[j] /= sum;
                sdp += (double)dk[j] * P[j];
            }
            double diff = log(sum) + beta * sdp - desired;
            if (fabs(diff) <= PERP_TOL)
                break;
            if (diff > 0.0) {
                bmin = beta;
                beta = (bmax == INFINITY) ? beta * 2.0 : (beta + bmax) / 2.0;
            } else {
                bmax = beta;
                beta = (bmin == -INFINITY) ? beta / 2.0 : (beta + bmin) / 2.0;
            }
        }
        for (int j = 0; j < k; j++) {
            s_nbr[i * k + j] = ik[j];
            s_p[i * k + j] = (float)P[j];
            sum_all += P[j];
        }
    }
    /* P_sym = (P + P^T) / sum(P + P^T); each directed edge carries its own part */
    const double inv = 1.0 / (2.0 * sum_all);
    for (int e = 0; e < n * k; e++)
        s_p[e] = (float)(s_p[e] * inv);
}

/* ---------------------------------------------------------------- octree */
static int s_ncell, s_overflow, s_depth_max;
static float s_root_c[D3], s_root_h[D3], s_sqw[MAX_DEPTH + 1];

static int new_cell(int depth, const float *pt, uint16_t point, uint16_t size)
{
    if (s_ncell >= TSNE_CELLS)
        return -1;
    cell_t *c = &s_cell[s_ncell];
    memcpy(c->bary, pt, sizeof c->bary);
    c->size = size;
    c->depth = (uint8_t)depth;
    c->leaf = 1;
    c->point = point;
    for (int q = 0; q < 8; q++)
        c->child[q] = -1;
    if (depth > s_depth_max)
        s_depth_max = depth;
    return s_ncell++;
}

static int octant(const float *pt, const float *ctr)
{
    return ((pt[0] >= ctr[0]) << 2) | ((pt[1] >= ctr[1]) << 1) | (pt[2] >= ctr[2]);
}

static void step_into(int q, float *ctr, float *half)
{
    for (int a = 0; a < D3; a++) {
        half[a] *= 0.5f;
        ctr[a] += ((q >> (2 - a)) & 1) ? half[a] : -half[a];
    }
}

static void insert(const float *pt, uint16_t idx)
{
    int cid = 0;
    float ctr[D3], half[D3];
    memcpy(ctr, s_root_c, sizeof ctr);
    memcpy(half, s_root_h, sizeof half);
    for (;;) {
        cell_t *c = &s_cell[cid];
        if (c->size == 0) {
            c->size = 1;
            memcpy(c->bary, pt, sizeof c->bary);
            c->point = idx;
            return;
        }
        if (!c->leaf) {
            for (int a = 0; a < D3; a++)
                c->bary[a] = (c->size * c->bary[a] + pt[a]) / (c->size + 1);
            c->size++;
            int q = octant(pt, ctr);
            if (c->child[q] < 0) {
                int nc = new_cell(c->depth + 1, pt, idx, 1);
                if (nc < 0) {               /* octree full: the point stays summarised in this cell */
                    s_overflow++;
                    return;
                }
                s_cell[cid].child[q] = (int16_t)nc;
                return;
            }
            step_into(q, ctr, half);
            cid = c->child[q];
            continue;
        }
        int dup = 1;
        for (int a = 0; a < D3; a++)
            dup &= fabsf(pt[a] - c->bary[a]) <= DUP_EPS;
        if (dup || c->depth >= MAX_DEPTH) {
            c->size++;                      /* sklearn: duplicate -> count only */
            return;
        }
        /* split the leaf: its content moves to a new child, then insert again here */
        int q = octant(c->bary, ctr);
        int nc = new_cell(c->depth + 1, c->bary, c->point, c->size);
        if (nc < 0) {
            s_overflow++;
            for (int a = 0; a < D3; a++)
                c->bary[a] = (c->size * c->bary[a] + pt[a]) / (c->size + 1);
            c->size++;
            return;
        }
        c = &s_cell[cid];
        c->child[q] = (int16_t)nc;
        c->leaf = 0;
    }
}

static void build_tree(const float *y, int n)
{
    float mn[D3], mx[D3];
    for (int a = 0; a < D3; a++)
        mn[a] = mx[a] = y[a];
    for (int i = 1; i < n; i++)
        for (int a = 0; a < D3; a++) {
            float v = y[i * D3 + a];
            if (v < mn[a]) mn[a] = v;
            if (v > mx[a]) mx[a] = v;
        }
    float wmax = 0.0f;
    for (int a = 0; a < D3; a++) {
        float s = (mx[a] > 0) ? 1.0f : (mx[a] < 0) ? -1.0f : 0.0f;
        float M = fmaxf(mx[a] * (1.0f + 1e-3f * s), mx[a] + 1e-3f);   /* sklearn bounds */
        s_root_c[a] = (M + mn[a]) / 2.0f;
        s_root_h[a] = (M - mn[a]) / 2.0f;
        wmax = fmaxf(wmax, M - mn[a]);
    }
    float w2 = wmax * wmax;
    for (int d = 0; d <= MAX_DEPTH; d++, w2 *= 0.25f)
        s_sqw[d] = w2;
    s_ncell = 0;
    float zero[D3] = {0, 0, 0};
    new_cell(0, zero, 0, 0);
    for (int i = 0; i < n; i++)
        insert(y + i * D3, (uint16_t)i);
}

/* repulsive force on point i (unnormalised) and its contribution to sum Q */
static double negative(const float *yi, float *neg)
{
    double sq = 0.0;
    int sp = 0;
    neg[0] = neg[1] = neg[2] = 0.0f;
    s_stack[sp++] = 0;
    while (sp) {
        const cell_t *c = &s_cell[s_stack[--sp]];
        float d[D3], d2 = 0.0f;
        int dup = 1;
        for (int a = 0; a < D3; a++) {
            d[a] = yi[a] - c->bary[a];
            d2 += d[a] * d[a];
            dup &= fabsf(d[a]) <= DUP_EPS;
        }
        if (dup && c->leaf)
            continue;
        if (c->leaf || s_sqw[c->depth] < THETA2 * d2) {
            float q = DOF / (DOF + d2);
            q = q * sqrtf(q);                     /* ^((dof + 1) / 2) = ^1.5 */
            sq += (double)c->size * q;
            float mult = c->size * q * q;
            for (int a = 0; a < D3; a++)
                neg[a] += mult * d[a];
        } else {
            for (int q = 7; q >= 0; q--)          /* pop order = sklearn's child order */
                if (c->child[q] >= 0)
                    s_stack[sp++] = c->child[q];
        }
    }
    return sq;
}

static void gradient(const float *y, int n, int k, float exag)
{
    double sum_q = 0.0;
    build_tree(y, n);
    for (int i = 0; i < n; i++)
        sum_q += negative(y + i * D3, s_grad + i * D3);
    if (sum_q < 2.220446049250313e-16)
        sum_q = 2.220446049250313e-16;
    const float inv = (float)(1.0 / sum_q);
    for (int e = 0; e < n * D3; e++)
        s_grad[e] = -s_grad[e] * inv;
    for (int i = 0; i < n; i++) {
        const float *yi = y + i * D3;
        for (int e = i * k; e < (i + 1) * k; e++) {
            const float *yj = y + s_nbr[e] * D3;
            float d[D3], d2 = 0.0f;
            for (int a = 0; a < D3; a++) {
                d[a] = yi[a] - yj[a];
                d2 += d[a] * d[a];
            }
            float q = DOF / (DOF + d2);
            float f = exag * s_p[e] * q * sqrtf(q);
            for (int a = 0; a < D3; a++) {
                s_grad[i * D3 + a] += f * d[a];
                s_grad[s_nbr[e] * D3 + a] -= f * d[a];
            }
        }
    }
    const float c = 2.0f * (DOF + 1.0f) / DOF;
    for (int e = 0; e < n * D3; e++)
        s_grad[e] *= c;
}

/* ---------------------------------------------------------------- optimiser */
static int descend(float *y, int n, int k, int it0, int it1, float momentum, float exag, float lr,
                   tsne_stats_t *st)
{
    int i;
    for (int e = 0; e < n * D3; e++) {
        s_upd[e] = 0.0f;
        s_gain[e] = 1.0f;
    }
    for (i = it0; i < it1; i++) {
        gradient(y, n, k, exag);
        double gn = 0.0;
        for (int e = 0; e < n * D3; e++) {
            float g = s_grad[e];
            if (s_upd[e] * g < 0.0f)
                s_gain[e] += 0.2f;
            else
                s_gain[e] *= 0.8f;
            if (s_gain[e] < MIN_GAIN)
                s_gain[e] = MIN_GAIN;
            g *= s_gain[e];
            s_upd[e] = momentum * s_upd[e] - lr * g;
            y[e] += s_upd[e];
            gn += (double)g * g;
        }
        if (s_ncell > st->cells_max)
            st->cells_max = s_ncell;
        if ((i + 1) % CHECK_EVERY == 0) {
            st->grad_norm = sqrt(gn);
            if (st->grad_norm <= MIN_GRAD_NORM)
                break;
        }
    }
    return i < it1 ? i : it1 - 1;
}

int tsne_run(const int16_t *x, int n, float perplexity, int max_iter, const float *init, float *y,
             tsne_stats_t *st)
{
    int k = (int)(3.0f * perplexity + 1.0f);
    if (k > n - 1)
        k = n - 1;
    if (n > TSNE_NMAX || k > TSNE_K || k < 1)
        return -1;
    memset(st, 0, sizeof *st);
    s_overflow = 0;
    s_depth_max = 0;
    joint_probabilities(x, n, k, perplexity);
    if (y != init)
        memcpy(y, init, sizeof(float) * D3 * n);
    float lr = (float)n / EXAG / 4.0f;
    if (lr < 50.0f)
        lr = 50.0f;
    int it = descend(y, n, k, 0, EXPLORE_ITER < max_iter ? EXPLORE_ITER : max_iter, 0.5f, EXAG, lr, st);
    if (max_iter > EXPLORE_ITER)
        it = descend(y, n, k, it + 1, max_iter, 0.8f, 1.0f, lr, st);
    st->n_iter = it;
    st->cell_overflow = s_overflow;
    st->tree_depth_max = s_depth_max;
    return 0;
}
