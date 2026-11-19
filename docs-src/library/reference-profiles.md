# Reference and completion profiles

Understand the scope of a native operation before comparing implementations or claiming coverage.

A formal contract describes a problem. A native profile describes the supported parameters, input assumptions, quality, and output behavior of a particular operation. The profile may be narrower than the full research problem. The [backend table](backends.md) is generated from the recorded compiled catalog, while each [family page](../problem/taxonomy.md#browse-the-families) links the corresponding contract.

## CPU references

The native CPU runtime supplies executable profiles across the catalog. Some profiles use bounded exact search; others are heuristic, numerical, sampling, or learned methods. Small exact reference implementations are useful for checking results even when they are unsuitable for a large production-sized input.

The Python reference modules are independent test oracles. They do not replace the native implementation when it fails or when a GPU is unavailable.

## GPU profiles

GPU support is specific to an operation, implementation, and parameter combination. Examples include integral-capacity restrictions for a flow kernel, a particular motif shape, or an uncapped enumeration profile. A GPU kernel can return a count while native code constructs or checks witnesses separately.

Treat “compiled”, “compatible”, and “validated” as separate facts. A compiled backend still needs the right input assumptions and matching evidence. Compare CPU and GPU results using the contract's semantics: ordering can differ, multiple optimal witnesses can be valid, and floating-point results may require explicit tolerances.

## Completion

An operation being present in the catalog does not make every theoretical variant available. Inspect required parameters, supported objectives, output limits, and the actual response. [Output completeness](outputs.md) and [quality guarantees](../problem/guarantees.md) explain what to preserve in downstream workflows.
