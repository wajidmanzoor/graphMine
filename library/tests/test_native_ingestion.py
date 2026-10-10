"""Independent CSV round trips and native graph construction boundaries."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
from test_native_binding import GPU, ROOT, WRAPPER, binding, library


@pytest.fixture(scope="session", autouse=True)
def evidence(request):
    files = [Path(__file__), WRAPPER]
    files += list((ROOT / "library/runtime").rglob("*.cpp"))
    files += list((ROOT / "library/runtime").rglob("*.hpp"))
    files += list((ROOT / "library/runtime").rglob("*.in"))
    files += [ROOT / "library/runtime/CMakeLists.txt"]
    files += [
        GPU / name
        for name in (
            "libgraphmine_runtime.so",
            "graphmine-native",
            "native-source-hashes.txt",
        )
    ]

    def snapshot():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    before = snapshot()
    yield
    unchanged = before == snapshot()
    if report := getattr(request.config.option, "xmlpath", None):
        Path(str(report) + ".metadata.json").write_text(
            json.dumps(
                {
                    "scope": "Native libcudf ingestion and C++ construction",
                    "source_files": before,
                    "sources_unchanged_during_run": unchanged,
                    "collected_test_count": len(request.session.items),
                },
                indent=2,
            )
            + "\n"
        )
    assert unchanged


@pytest.fixture(params=[0, 1])
def gpu(request):
    return request.param


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_cudf_roundtrips_adversarial_cells_without_python_parsing(
    tmp_path, gpu, ending
):
    cells = [
        "",
        "001",
        "-0",
        "+1",
        "NA",
        "null",
        "true",
        "0007",
        "a,b",
        'a"b',
        '"quoted"',
        "one\ntwo",
        "one\r\ntwo",
        " Café ",
        "علی",
        "🧬",
        "9007199254740993",
        "9223372036854775808",
        "0.1000000000000000001",
        "   ",
    ]
    path = tmp_path / "values.csv"
    lib = library(GPU)
    for width in (1, 2, 4):
        names = [f"column-{i}" for i in range(width)]
        rows = [
            [cells[(r + c) % len(cells)] for c in range(width)]
            for r in range(len(cells))
        ]
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator=ending, quoting=csv.QUOTE_ALL)
        writer.writerow(names)
        writer.writerows(rows)
        content = ("\ufeff" + output.getvalue()).encode()
        path.write_bytes(content)
        result = lib.read_csv(path, gpu_device=gpu)
        assert result["table"]["rows"] == [
            dict(zip(names, row, strict=True)) for row in rows
        ]
        assert (
            result["provenance"]["input_sha256"] == hashlib.sha256(content).hexdigest()
        )
        assert result["provenance"]["reader"] == "libcudf"
        assert result["provenance"]["gpu_device"] == gpu
        assert result["complete"] is True


@pytest.mark.parametrize(
    "content,message",
    [
        (b"id,value\n1,2,3\n", "different number"),
        (b"id,value\n1\n", "different number"),
        (b"id,id\n1,2\n", "unique"),
        (b",value\n1,2\n", "nonempty"),
        (b'id,value\n1,"open\n', "unterminated"),
        (b'id,value\n1,"closed"tail\n', "closing quote"),
        (b'id,value\n1,un"quoted\n', "enclose"),
        (b"id,value\n1,\xff\n", "UTF-8"),
        (b"id,value\n1,\xc0\xaf\n", "UTF-8"),
        (b"id,value\n1,\xed\xa0\x80\n", "UTF-8"),
        (b"id,value\n1,\xf4\x90\x80\x80\n", "UTF-8"),
        (b"id,value\n1,\xe2\x82", "UTF-8"),
        (b"id,value\n1,\x00\n", "NUL"),
        (b"", "empty"),
    ],
)
def test_malformed_csv_never_becomes_a_complete_table(tmp_path, gpu, content, message):
    path = tmp_path / "bad.csv"
    path.write_bytes(content)
    with pytest.raises(binding.NativeError, match=message):
        library(GPU).read_csv(path, gpu_device=gpu)


def test_projection_keeps_ids_attributes_parallel_edges_and_loop_policy(tmp_path, gpu):
    path = tmp_path / "mapped.csv"
    path.write_text(
        "employee,partner,id,source_label,target_label,source.department,amount,reference\n"
        "001,9007199254740993,e1,Ava,Ben,Design,9007199254740993,0007\n"
        "001,9007199254740993,e2,Ava,Ben,Design,0.1,NA\n"
        "001,001,e3,Ava,Ava,Design,-0.2,zero\n"
    )
    result = library(GPU).read_graph(
        path, source_column="employee", target_column="partner", gpu_device=gpu
    )
    graph = result["graph"]
    assert graph["vertices"] == [
        {"id": "001", "label": "Ava", "attributes": {"department": "Design"}},
        {"id": 9007199254740993, "label": "Ben"},
    ]
    assert [edge["id"] for edge in graph["edges"]] == ["e1", "e2", "e3"]
    assert graph["edges"][0]["attributes"] == {
        "amount": 9007199254740993,
        "reference": "0007",
    }
    assert graph["graph"]["allows_parallel_edges"] is True
    assert graph["graph"]["allows_self_loops"] is True
    assert graph["graph"]["attributes"]["ingestion"] == result["provenance"]
    assert result["provenance"]["source_column"] == "employee"


@pytest.mark.parametrize(
    "text",
    [
        "# comment\nsource target weight timestamp\n+1 2 1.5 10\n% comment\n2 3 2.5 11\n",
        "source,target,weight,timestamp\n+1,2,1.5,10\n2,3,2.5,11\n",
        "+1\t2\t1.5\t10\n2\t3\t2.5\t11\n",
    ],
)
def test_edge_lists_use_cudf_and_native_numeric_mapping(tmp_path, gpu, text):
    path = tmp_path / "edges.txt"
    path.write_text(text)
    result = library(GPU).read_graph(path, directed=True, gpu_device=gpu)
    assert result["graph"]["vertices"] == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert result["graph"]["edges"] == [
        {"id": 0, "source": 1, "target": 2, "weight": 1.5, "timestamp": 10},
        {"id": 1, "source": 2, "target": 3, "weight": 2.5, "timestamp": 11},
    ]
    assert result["graph"]["graph"]["directed"] is True


def test_edge_lists_allow_absent_optional_values_without_losing_endpoints(
    tmp_path, gpu
):
    path = tmp_path / "edges.txt"
    path.write_text("a b\nb c 1.5\nc a 2.5 11\n")
    result = library(GPU).read_graph(path, gpu_device=gpu)
    assert result["graph"]["edges"] == [
        {"id": 0, "source": "a", "target": "b"},
        {"id": 1, "source": "b", "target": "c", "weight": 1.5},
        {"id": 2, "source": "c", "target": "a", "weight": 2.5, "timestamp": 11},
    ]


@pytest.mark.parametrize(
    "text,message",
    [
        ("employee,partner\na,b\n", "From and To"),
        ("source,target,source_label\na,b,First\na,c,Second\n", "Conflicting"),
        ("source,target,id\na,b,same\nb,c,same\n", "duplicate edge id"),
        ("source,target\n,1\n", "empty"),
        ("source,target\n9223372036854775808,1\n", "native range"),
        ("source,target,weight\na,b,9007199254740993\n", "loses precision"),
        ("source,target,weight\na,b,NaN\n", "finite"),
        ("source,target,weight\na,b,1e309\n", "finite"),
        ("source,target,timestamp\na,b,1.5\n", "integer"),
        ("source,target,amount\na,b,9223372036854775808\n", "native range"),
    ],
)
def test_projection_refuses_ambiguous_or_lossy_values(tmp_path, gpu, text, message):
    path = tmp_path / "bad.csv"
    path.write_text(text)
    with pytest.raises(binding.NativeError, match=message):
        library(GPU).read_graph(path, gpu_device=gpu)


def test_explicit_string_ids_and_empty_table(tmp_path, gpu):
    path = tmp_path / "strings.csv"
    path.write_text("source,target\n9223372036854775808,1\n")
    result = library(GPU).read_graph(path, id_type="string", gpu_device=gpu)
    assert result["graph"]["vertices"] == [{"id": "9223372036854775808"}, {"id": "1"}]
    path.write_text("source,target\n")
    result = library(GPU).read_graph(path, gpu_device=gpu)
    assert result["graph"]["vertices"] == result["graph"]["edges"] == []
