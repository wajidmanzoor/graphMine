"""A byte-budgeted LRU for immutable parsed JSON, with one cold reader at a time."""

import json
import os
import sys
from collections import OrderedDict
from threading import RLock


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def file_info(path):
    from .analytics import AnalyticsError

    try:
        return path.stat()
    except FileNotFoundError as exc:
        raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409) from exc


def read_json(path, limit):
    from .analytics import AnalyticsError

    try:
        handle = path.open("rb")
    except FileNotFoundError as exc:
        raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409) from exc
    with handle:
        before = os.fstat(handle.fileno())
        if limit is not None and before.st_size > limit:
            raise AnalyticsError("Workflow artifact exceeds the byte budget", "resource_limit")
        raw = handle.read(before.st_size + 1)
        if len(raw) != before.st_size or stamp(os.fstat(handle.fileno())) != stamp(before):
            raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AnalyticsError("The saved artifact could not be read.", "data_integrity", 409) from exc
    if stamp(file_info(path)) != stamp(before):
        raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409)
    return value


def memory_size(value, ceiling):
    """Conservative Python allocation estimate, bounded by the admission budget.

    Parsed JSON is an acyclic tree. Count repeated references independently to
    avoid an additional unbounded set of object IDs; shared keys only overcount.
    Iterator frames keep traversal memory proportional to nesting depth.
    """
    total, pending = 0, [iter((value,))]
    while pending:
        try:
            item = next(pending[-1])
        except StopIteration:
            pending.pop(); continue
        total += sys.getsizeof(item)
        if total > ceiling:
            return total
        if isinstance(item, dict):
            pending.append(iter(item.values())); pending.append(iter(item.keys()))
        elif isinstance(item, (list, tuple)):
            pending.append(iter(item))
    return total


class ResultCache:
    def __init__(self, max_bytes, max_entries=8):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries, self.bytes = OrderedDict(), 0
        self.lock, self.reader = RLock(), RLock()

    def __len__(self):
        with self.lock:
            return len(self.entries)

    def clear(self):
        with self.lock:
            self.entries.clear(); self.bytes = 0

    def _hit(self, key):
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key][0], True
            # Retire obsolete generations even if the next parse fails.
            for previous in list(self.entries):
                if previous[0] == key[0]:
                    self.bytes -= self.entries.pop(previous)[1]
        return None, False

    def read(self, path, limit):
        from .analytics import AnalyticsError

        def identity():
            info = file_info(path)
            if limit is not None and info.st_size > limit:
                raise AnalyticsError("Workflow artifact exceeds the byte budget", "resource_limit")
            return (str(path), *stamp(info))
        key = identity()
        value, found = self._hit(key)
        if found:
            return value
        # A burst of misses cannot parse many large artifacts simultaneously.
        with self.reader:
            key = identity(); value, found = self._hit(key)
            if found:
                return value
            value = read_json(path, limit)
            if identity() != key:
                raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409)
            weight = memory_size(value, self.max_bytes) + memory_size(key, self.max_bytes) + 512
            if weight <= self.max_bytes:
                with self.lock:
                    while self.entries and (self.bytes + weight > self.max_bytes or len(self.entries) >= self.max_entries):
                        self.bytes -= self.entries.popitem(last=False)[1][1]
                    self.entries[key] = value, weight; self.bytes += weight
            return value
