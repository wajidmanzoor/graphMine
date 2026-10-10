"""Thin bindings to the standalone C++/CUDA core; no Python graph algorithms.

The native library owns operation contracts, family membership, validation,
backend selection and result computation. This module only transports JSON
through its versioned C ABI. ``graphmine.run`` remains the migration reference
API until the remaining native profiles have been ported and verified.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
from copy import deepcopy


class NativeError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NativeLibrary:
    def __init__(self, library_path=None):
        path = (
            str(library_path)
            if library_path is not None
            else os.environ.get("GRAPHMINE_NATIVE_LIBRARY")
            or ctypes.util.find_library("graphmine_runtime")
        )
        if not path:
            raise NativeError(
                "backend_unavailable",
                "Install libgraphmine_runtime or set GRAPHMINE_NATIVE_LIBRARY",
            )
        self._library = ctypes.CDLL(path)
        self._library.graphmine_runtime_abi_version.restype = ctypes.c_int
        self._library.graphmine_runtime_abi_version.argtypes = []
        if self._library.graphmine_runtime_abi_version() != 1:
            raise NativeError("abi_mismatch", "Unsupported native runtime ABI")
        self._library.graphmine_runtime_request.argtypes = [
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._library.graphmine_runtime_request.restype = ctypes.c_int
        self._library.graphmine_runtime_free.argtypes = [ctypes.c_void_p]
        self._library.graphmine_runtime_free.restype = None
        self._catalog = self.request({"command": "catalog"})

    def request(self, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        output = ctypes.c_void_p()
        length = ctypes.c_size_t()
        status = self._library.graphmine_runtime_request(
            raw, len(raw), ctypes.byref(output), ctypes.byref(length)
        )
        if status != 0:
            raise NativeError("resource_limit", "Native response allocation failed")
        try:
            response = json.loads(ctypes.string_at(output, length.value))
        finally:
            self._library.graphmine_runtime_free(output)
        if "error" in response:
            raise NativeError(response["error"]["code"], response["error"]["message"])
        return response

    def catalog(self):
        return deepcopy(self._catalog)

    def read_csv(self, path, *, columns=None, gpu_device=0, max_rows=100000):
        """Use libcudf; retain text until the caller supplies explicit mapping."""
        request = {
            "command": "read_csv",
            "path": os.fspath(path),
            "gpu_device": gpu_device,
            "max_rows": max_rows,
        }
        if columns is not None:
            request["columns"] = columns
        return self.request(request)

    def read_graph(
        self,
        path,
        *,
        source_column=None,
        target_column=None,
        directed=False,
        id_type="canonical",
        gpu_device=0,
        max_rows=100000,
    ):
        """Read tabular files through libcudf and construct the graph in C++."""
        request = {
            "command": "read_graph",
            "path": os.fspath(path),
            "directed": directed,
            "id_type": id_type,
            "gpu_device": gpu_device,
            "max_rows": max_rows,
        }
        if source_column is not None:
            request["source_column"] = source_column
        if target_column is not None:
            request["target_column"] = target_column
        return self.request(request)

    def list_algorithms(self, *, family=None):
        return [
            deepcopy(card)
            for card in self._catalog["operations"]
            if family is None or card["family"] == family
        ]

    def list_families(self):
        return deepcopy(self._catalog["families"])

    def family(self, family_id):
        if family_id not in {row["id"] for row in self._catalog["families"]}:
            raise NativeError("invalid_input", "Unknown native family")
        return Family(self, family_id)

    def run(
        self,
        operation,
        graph,
        *,
        parameters=None,
        device="auto",
        backend="auto",
        gpu_device=0,
        budget=None,
    ):
        if hasattr(graph, "to_canonical"):
            graph = graph.to_canonical()
        request = {
            "command": "run",
            "operation": operation,
            "graph": graph,
            "parameters": {} if parameters is None else parameters,
            "device": device,
            "backend": backend,
            "gpu_device": gpu_device,
        }
        if budget is not None:
            request["budget"] = budget
        return self.request(request)


class Family:
    def __init__(self, library, family_id):
        self._library = library
        self.id = family_id

    def list_algorithms(self):
        return self._library.list_algorithms(family=self.id)

    def __getattr__(self, name):
        operation = name.replace("_", "-")
        if operation not in {card["id"] for card in self.list_algorithms()}:
            raise AttributeError(name)

        def execute(graph, *, parameters=None, **options):
            return self._library.run(operation, graph, parameters=parameters, **options)

        execute.__name__ = name
        return execute


__all__ = ["Family", "NativeError", "NativeLibrary"]
