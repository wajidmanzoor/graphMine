"""Save the benchmark's published schema images and loading pages locally."""

import hashlib
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("downloads", Path(__file__).with_name("download-benchmarks.py"))
downloads = module_from_spec(spec)
spec.loader.exec_module(downloads)

DATASETS = {
    "yelp": ("Yelp", "yelp"),
    "movielens-32m": ("MovieLens 32M", "ml32m"),
    "movielens-genome": ("MovieLens Tag Genome", "mlgenome"),
    "amazon": ("Amazon", "amazon"),
    "stackoverflow": ("Stack Overflow", "stackof"),
    "ontime": ("OnTime", "ontime"),
    "fars": ("FARS", "fars"),
    "ldbc-snb": ("LDBC SNB", "snb"),
}


class SchemaAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.blocks = []
        self.block = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img" and "schema" in values.get("src", "").lower():
            self.images.append(values["src"])
        if tag == "pre":
            self.block = []

    def handle_data(self, text):
        if self.block is not None:
            self.block.append(text)

    def handle_endtag(self, tag):
        if tag == "pre" and self.block is not None:
            self.blocks.append("".join(self.block))
            self.block = None


def main():
    root = Path(sys.argv[1])
    for identifier, (name, page) in DATASETS.items():
        directory = root / identifier / "schemas"
        directory.mkdir(parents=True, exist_ok=True)
        schemas = []
        for platform in ["neo4j", "tigergraph", "puppygraph", "graphframes"]:
            url = f"{downloads.SITE}/workloads/{page}-{platform}.html"
            saved_page = directory / f"{platform}.html"
            try:
                downloads.fetch(url, saved_page)
                parser = SchemaAssets()
                parser.feed(saved_page.read_text())
                for index, relative in enumerate(dict.fromkeys(parser.images)):
                    image_url = urljoin(url, relative)
                    filename = f"{platform}-{index}.png"
                    target = directory / filename
                    downloads.fetch(image_url, target)
                    signature = target.read_bytes()[:8]
                    extension = ".png" if signature == b"\x89PNG\r\n\x1a\n" else (
                        ".gif" if signature.startswith(b"GIF8") else
                        ".jpg" if signature.startswith(b"\xff\xd8\xff") else None
                    )
                    if extension is None:
                        raise ValueError("Schema response was not a supported image")
                    if extension != ".png":
                        filename = f"{platform}-{index}{extension}"
                        target = target.replace(directory / filename)
                    schemas.append({
                        "platform": platform, "file": filename, "url": image_url,
                        "page": url, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    })
                if parser.blocks:
                    (directory / f"{platform}-loading-and-queries.txt").write_text("\n\n".join(parser.blocks) + "\n")
            except Exception as error:
                print(f"Unavailable schema page {url}: {error}", flush=True)
        downloads.write_json(directory / "manifest.json", {"id": identifier, "name": name, "schemas": schemas})
        print(f"Saved {name}: {len(schemas)} published schema diagrams", flush=True)


if __name__ == "__main__":
    main()
