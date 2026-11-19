# Python bindings

Use Python to pass structured requests to the compiled library.

Install the package after [building the native runtime](install.md):

```sh
python -m pip install -e python/graphmine
```

Give the binding an explicit shared-library path:

```python
import json
from pathlib import Path
from graphmine.native import NativeLibrary

library = NativeLibrary("build/native-cpu/libgraphmine_runtime.so")
graph = json.loads(Path("library/examples/data/triangle.json").read_text())
result = library.run("triangle-counting", graph, device="cpu")
print(result)
```

`library.catalog()` returns the native catalog. `library.list_families()` lists family metadata. `library.validate(operation, graph, parameters=..., device=...)` checks a prospective request. The family interface offers the same native operations grouped by family.

The binding transports JSON through the versioned C ABI, releases response memory, and raises `NativeError` for structured runtime errors. Its `code` attribute identifies the failure class. It does not silently run a Python graph algorithm when a native backend is unavailable.

[Binding source](https://github.com/wajidmanzoor/graphMine/blob/main/python/graphmine/graphmine/native/__init__.py) · [Native code reference](code-reference.md)
