# Preliminary build, excluded from release admission

These reports belong to the first release build, which omitted the three parallel Louvain/Leiden GPU backends because `/tmp/pggc-deps/install` no longer contained its dependency files. Validation was interrupted after this discrepancy was found. These artifacts are retained for diagnosis and are not inputs to the production evidence catalog.

The final build restores Kokkos and KokkosKernels 4.7.00 under `library/build/native-dependencies/`. Final reports are recorded in the parent directory and its `native/` subdirectory, after the complete catalog is checked against the previous release.
