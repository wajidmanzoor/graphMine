# Spectral & topology

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Eigenvectors, smoothing signals over the graph, or shape across thresholds. Compute Laplacian eigenpairs, denoise graph signals, or track topological features through a filtration.

**Start with this question:** Eigenvectors, smoothing signals over the graph, or shape across thresholds.

[Explore these operations](../explorer.md#family/spectral) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Graph Laplacian Eigenpairs](#graph_laplacian_eigenpairs)
- [Graph Signal Denoising and Trend Filtering](#graph_signal_denoising)
- [Flag-Complex Persistent Homology](#persistent_homology)

## Graph Laplacian Eigenpairs {#graph_laplacian_eigenpairs}

Compute selected eigenpairs of the combinatorial or symmetric normalized Laplacian of a nonnegative undirected graph.

$$
Lx_i=\lambda_i x_i
$$

L is the combinatorial or symmetric normalized Laplacian specified by the contract.

**Example question:** “Compute the smallest Laplacian eigenvalues and their vectors.”

**Input assumptions.** direction: undirected; weights: optional finite nonnegative weights default one; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Floating-point eigenpairs with explicit residual and orthogonality tolerances.

**Required outputs:** `eigenvalues`, `eigenvectors`, `vertex_order`, `residual_norms`, `converged`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`laplacian-eigenpairs`](../explorer.md#problem/graph_laplacian_eigenpairs) | `cpp` | — | Numerical |

**`laplacian-eigenpairs`** — Native LAPACK symmetric eigensolver with independently recomputed absolute residual and orthogonality checks. Combinatorial or symmetric-normalized Laplacian, including isolates. Undirected input; reject loops and negative weights, sum parallel weights. Dense solver uses work budgets; no iteration parameter.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run laplacian-eigenpairs INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_laplacian_eigenpairs) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/63_graph_laplacian_eigenpairs/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [CuPy: A NumPy-Compatible Library for NVIDIA GPU Calculations](https://learningsys.github.io/nips17/schedule.html). LearningSys workshop at NIPS 2017, 2017 · [Author code](https://github.com/cupy/cupy).
- [CuPy: A NumPy-Compatible Library for NVIDIA GPU Calculations](https://learningsys.github.io/nips17/schedule.html). LearningSys workshop at NIPS 2017, 2017 · [Author code](https://github.com/cupy/cupy).
- [CuPy: A NumPy-Compatible Library for NVIDIA GPU Calculations](https://learningsys.github.io/nips17/schedule.html). LearningSys workshop at NIPS 2017, 2017 · [Author code](https://github.com/cupy/cupy).

## Graph Signal Denoising and Trend Filtering {#graph_signal_denoising}

Estimate a vertex signal from noisy observations using a declared graph-difference regularizer.

$$
\min_x\frac12\|x-y\|_2^2+\lambda R_G(x)
$$

y is the observed signal; R is the declared graph-difference regularizer.

**Example question:** “Smooth these vertex measurements while respecting the graph.”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: required observed signal; edge attributes: ignored.

**Guarantee.** Numerical optimization with disclosed stopping conditions; different regularizers define different variants.

**Required outputs:** `estimated_signal`, `objective_value`, `converged`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-signal-denoising`](../explorer.md#problem/graph_signal_denoising) | `cpp` | — | Numerical |

**`graph-signal-denoising`** — Minimize half squared signal error plus Laplacian quadratic, weighted total variation, or explicit graph-trend penalty. Native positive-definite solve or accelerated feasible-dual optimization; tolerance bounds objective gap, with a separate L2 solution-error bound. Undirected input, no loops, nonnegative summed parallel weights.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-signal-denoising INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_signal_denoising) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/59_graph_signal_denoising/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Trend Filtering on Graphs](https://arxiv.org/abs/1410.7690). AISTATS 2015, 2014 · [Author code](https://cseweb.ucsd.edu/~yuxiangw/codes/gtf_code.zip).
- [Trend Filtering on Graphs](https://arxiv.org/abs/1410.7690). AISTATS 2015, 2014 · [Author code](https://cseweb.ucsd.edu/~yuxiangw/codes/gtf_code.zip).
- [Trend Filtering on Graphs](https://arxiv.org/abs/1410.7690). AISTATS 2015, 2014 · [Author code](https://github.com/gunrock/gunrock).

## Flag-Complex Persistent Homology {#persistent_homology}

Compute persistence intervals over a declared prime field for the flag-complex filtration induced by nonnegative undirected edge filtration values.

$$
K_a\subseteq K_b\ (a\le b),\qquad [b_i,d_i)
$$

The flag-complex filtration yields birth/death intervals over the declared prime field.

**Example question:** “When do connected components and holes appear and disappear?”

**Input assumptions.** direction: undirected; weights: required finite nonnegative filtration values; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mathematical objective; implementations must declare approximation and termination status.

**Required outputs:** `intervals`, `essential_interval_convention`, `coefficient_field`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`persistent-homology`](../explorer.md#problem/persistent_homology) | `cpp` | — | Exact |

**`persistent-homology`** — Exact sparse boundary reduction of a flag complex over a declared prime field. Vertices start at zero; include cofaces needed to compute deaths in requested dimensions. Undirected input; reject loops, require nonnegative weights, keep minimum parallel filtration. Optional cutoff marks unpaired intervals right-censored.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run persistent-homology INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/persistent_homology) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/67_persistent_homology/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU-Accelerated Computation of Vietoris-Rips Persistence Barcodes](https://arxiv.org/abs/2003.07989). arXiv, revised 2026, 2020 · [Author code](https://github.com/simonzhang00/ripser-plusplus).
