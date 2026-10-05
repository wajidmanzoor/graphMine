/* CUDA-MS single-result completion, 2026-10-04.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The relaxation supplies a feasible incumbent, never an upper bound.
 * Every clique belongs to its largest vertex's search tree. Each GPU worker
 * exhausts disjoint root trees, pruning only with proper coloring bounds.
 */
#include <algorithm>
#include <cstdint>
#include <limits>
#include <new>
#include <vector>

namespace {
using ms_word = unsigned long long;

__device__ int ms_first(const ms_word* bits, int words) {
    for (int w = 0; w < words; ++w)
        if (bits[w]) return 64*w + __ffsll(bits[w]) - 1;
    return -1;
}

// Greedy independent color classes. The first i vertices use at most
// bounds[i-1] colors, including after later vertices have been branched away.
__device__ int ms_color(ms_word* todo, ms_word* available,
                        const ms_word* adjacency, int words,
                        int* order, int* bounds) {
    int count = 0, color = 0;
    while (ms_first(todo, words) >= 0) {
        ++color;
        for (int w = 0; w < words; ++w) available[w] = todo[w];
        for (int v = ms_first(available, words); v >= 0; v = ms_first(available, words)) {
            order[count] = v;
            bounds[count++] = color;
            todo[v/64] &= ~(1ULL << (v%64));
            available[v/64] &= ~(1ULL << (v%64));
            for (int w = 0; w < words; ++w)
                available[w] &= ~adjacency[static_cast<size_t>(v)*words+w];
        }
    }
    return count;
}

__global__ void ms_exact_search(const ms_word* adjacency, const ms_word* allowed,
                                int n, int words, int* scratch, size_t stride,
                                int* global_best, int* sizes, int* witnesses) {
    // One independent depth-first traversal per worker. No shared scratch or
    // stack limits from device recursion; the stack has n explicitly allocated levels.
    int* base = scratch + static_cast<size_t>(blockIdx.x)*stride;
    int* order = base;
    int* bounds = order + static_cast<size_t>(n)*n;
    int* cursor = bounds + static_cast<size_t>(n)*n;
    int* chosen = cursor + n;
    ms_word* todo = reinterpret_cast<ms_word*>(chosen + n);
    ms_word* available = todo + words;
    int* witness = witnesses + static_cast<size_t>(blockIdx.x)*n;
    int local_best = 0;
    sizes[blockIdx.x] = 0;

    for (int root = blockIdx.x; root < n; root += gridDim.x) {
        if (!(allowed[root/64] & (1ULL << (root%64)))) continue;
        chosen[0] = root;
        if (atomicAdd(global_best, 0) == 0) {
            witness[0] = root;
            local_best = 1;
            sizes[blockIdx.x] = 1;
            atomicMax(global_best, 1);
        }
        for (int w = 0; w < words; ++w) {
            const ms_word before = w < root/64 ? ~0ULL :
                (w == root/64 ? ((1ULL << (root%64))-1) : 0ULL);
            todo[w] = adjacency[static_cast<size_t>(root)*words+w] & allowed[w] & before;
        }
        cursor[0] = ms_color(todo, available, adjacency, words, order, bounds)-1;
        int level = 0;
        while (level >= 0) {
            const size_t offset = static_cast<size_t>(level)*n;
            const int at = cursor[level];
            if (at < 0 || level+1+bounds[offset+at] <= atomicAdd(global_best, 0)) {
                --level;
                continue;
            }
            const int v = order[offset+at];
            --cursor[level];
            chosen[level+1] = v;
            const int size = level+2;
            if (size > local_best) {
                for (int i = 0; i < size; ++i) witness[i] = chosen[i];
                local_best = size;
                sizes[blockIdx.x] = size;
                atomicMax(global_best, size);
            }
            for (int w = 0; w < words; ++w) todo[w] = 0;
            for (int i = 0; i < at; ++i) {
                const int u = order[offset+i];
                if (adjacency[static_cast<size_t>(v)*words+u/64] & (1ULL << (u%64)))
                    todo[u/64] |= 1ULL << (u%64);
            }
            // With n chosen vertices no candidates can remain (no self loops).
            if (ms_first(todo, words) >= 0) {
                ++level;
                const size_t child = static_cast<size_t>(level)*n;
                cursor[level] = ms_color(todo, available, adjacency, words,
                                         order+child, bounds+child)-1;
            }
        }
    }
}

struct ms_device_buffer {
    void* data = nullptr;
    ~ms_device_buffer() { if (data) cudaFree(data); }
    bool allocate(size_t bytes) { return cudaMalloc(&data, bytes) == cudaSuccess; }
};
} // namespace

extern "C" int complete_cuda_clique(char** graph, int n, t_bitmask allowed,
                                     t_bitmask result) {
    if (n < 0 || !result) return -1;
    if (n == 0) { mask_zeroall(result, 0); return 0; }
    try {
        const int words = (n-1)/64+1;
        const size_t nn = static_cast<size_t>(n);
        if (nn > (std::numeric_limits<size_t>::max()/sizeof(int)-4*static_cast<size_t>(words)-2*nn-1)/nn/2)
            return -1;
        std::vector<ms_word> matrix(nn*words, 0), permitted(words, 0);
        std::vector<int> seed;
        for (int v = 0; v < n; ++v) {
            if (!graph || !graph[v]) return -1;
            const bool valid = !allowed || (allowed[v/64] & (1ULL << (v%64)));
            if (valid) permitted[v/64] |= 1ULL << (v%64);
            if (valid && (result[v/64] & (1ULL << (v%64)))) {
                bool adjacent = true;
                for (int u : seed) adjacent &= graph[u][v] && graph[v][u];
                if (adjacent) seed.push_back(v);
            }
            for (int u = 0; u < n; ++u)
                if (v != u && graph[v][u]) matrix[static_cast<size_t>(v)*words+u/64] |= 1ULL << (u%64);
        }
        mask_zeroall(result, n);
        for (int v : seed) result[v/64] |= 1ULL << (v%64);
        int best = static_cast<int>(seed.size());
        size_t free_bytes, total_bytes;
        if (cudaMemGetInfo(&free_bytes, &total_bytes) != cudaSuccess) return -1;
        // Round to an even number of ints so bitset scratch stays 8-byte aligned.
        const size_t stride = (2*nn*nn+2*nn+4*words+1) & ~size_t(1);
        const size_t budget = std::min(free_bytes/2,
            std::max(size_t(512)*1024*1024, stride*sizeof(int)));
        const int workers = static_cast<int>(std::min(std::min(nn, size_t(32)), budget/(stride*sizeof(int))));
        if (workers < 1) return -1;
        ms_device_buffer d_matrix, d_allowed, d_scratch, d_best, d_sizes, d_witnesses;
        if (!d_matrix.allocate(matrix.size()*sizeof(ms_word)) ||
            !d_allowed.allocate(permitted.size()*sizeof(ms_word)) ||
            !d_scratch.allocate(workers*stride*sizeof(int)) ||
            !d_best.allocate(sizeof(int)) || !d_sizes.allocate(workers*sizeof(int)) ||
            !d_witnesses.allocate(workers*nn*sizeof(int))) return -1;
        if (cudaMemcpy(d_matrix.data, matrix.data(), matrix.size()*sizeof(ms_word), cudaMemcpyHostToDevice) != cudaSuccess ||
            cudaMemcpy(d_allowed.data, permitted.data(), permitted.size()*sizeof(ms_word), cudaMemcpyHostToDevice) != cudaSuccess ||
            cudaMemcpy(d_best.data, &best, sizeof(int), cudaMemcpyHostToDevice) != cudaSuccess) return -1;
        ms_exact_search<<<workers, 1>>>(static_cast<ms_word*>(d_matrix.data),
            static_cast<ms_word*>(d_allowed.data), n, words, static_cast<int*>(d_scratch.data),
            stride, static_cast<int*>(d_best.data), static_cast<int*>(d_sizes.data),
            static_cast<int*>(d_witnesses.data));
        if (cudaGetLastError() != cudaSuccess || cudaDeviceSynchronize() != cudaSuccess) return -1;
        std::vector<int> sizes(workers), witness(n);
        if (cudaMemcpy(sizes.data(), d_sizes.data, workers*sizeof(int), cudaMemcpyDeviceToHost) != cudaSuccess) return -1;
        const int owner = static_cast<int>(std::max_element(sizes.begin(), sizes.end())-sizes.begin());
        if (sizes[owner] > best) {
            best = sizes[owner];
            if (cudaMemcpy(witness.data(), static_cast<int*>(d_witnesses.data)+owner*nn,
                           best*sizeof(int), cudaMemcpyDeviceToHost) != cudaSuccess) return -1;
            mask_zeroall(result, n);
            for (int i = 0; i < best; ++i) result[witness[i]/64] |= 1ULL << (witness[i]%64);
        }
        return best;
    } catch (const std::bad_alloc&) { return -1; }
}
