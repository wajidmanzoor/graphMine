"""Include generated API pages in the site's ordinary navigation and search."""
import json
from pathlib import Path


def on_config(config):
    generated=Path(config.docs_dir)/'library/api/navigation.json'
    if not generated.is_file():
        raise RuntimeError('Generate the native reference with node tools/build_code_docs.mjs before building the site.')
    pages=json.loads(generated.read_text())
    for section in config.nav:
        if 'Library' in section:
            for item in section['Library']:
                if item.get('Code reference') == 'library/code-reference.md':
                    item['Code reference'] = [
                        {'Overview':'library/code-reference.md'},
                        {'Find a function':'library/api/index.md'},
                        {'Browse files':'library/api/files.md'},
                        *pages,
                    ]
    return config


def on_page_content(html, page, config, files):
    if page.meta.get('native_reference'):
        # Keep the sidebar focused on functions, without repeating Parameters
        # and Return value beneath every function in a large source file.
        def trim(items):
            for item in items:
                item.children = [child for child in item.children if child.level <= 2]
                trim(item.children)
        trim(page.toc.items)
    return html
