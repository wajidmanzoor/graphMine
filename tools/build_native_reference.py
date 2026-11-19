#!/usr/bin/env python3
"""Build readable, source-checked function reference pages from Doxygen XML."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / 'tools/code_docs/function-notes'
OUTPUT = ROOT / 'docs-src/library/api'
BINDING = ROOT / 'tools/code_docs/source-manifest.json'
GROUPS = ['Public API', 'Graph core', 'Runtime', 'Algorithms', 'Backends']


def text(node):
    return ''.join(node.itertext()).strip() if node is not None else ''


def group_for(path):
    if path.startswith('library/include/'): return 'Public API'
    if path.startswith('library/src/core/'): return 'Graph core'
    if path.startswith(('library/runtime/families/', 'library/src/problems/')): return 'Algorithms'
    if path.startswith('library/src/backends/'): return 'Backends'
    return 'Runtime'


def slug(path):
    return re.sub(r'[^a-zA-Z0-9_-]', '-', path.removeprefix('library/')).lower()


def parameter_key(parameter, index):
    return parameter['name'] or f'${index + 1}'


def clean_name(value):
    return re.sub(r'anonymous_namespace\{[^}]+\}::', '', value)


def display_file(function):
    declaration = function.get('declaration_file', '')
    return declaration if declaration.startswith('library/include/') else function['file']


def extract(xml_directory):
    functions, types, files = {}, [], set()
    for path in sorted(xml_directory.glob('*.xml')):
        if path.name in {'index.xml', 'Doxyfile.xml'}: continue
        tree = ET.parse(path)
        compound = tree.find('compounddef')
        if compound is None: continue
        location = compound.find('location')
        source = location.get('file', '') if location is not None else ''
        if source.startswith('library/') and (ROOT/source).is_file(): files.add(source)
        if compound.get('kind') in {'class', 'struct', 'union'} and source:
            fields = []
            for member in compound.findall('.//memberdef[@kind="variable"]'):
                fields.append({'name':text(member.find('name')), 'type':text(member.find('type')), 'description':text(member.find('briefdescription'))})
            types.append({'name':text(compound.find('compoundname')), 'file':source, 'id':compound.get('id'), 'description':text(compound.find('briefdescription')), 'fields':fields})
        for member in tree.findall('.//memberdef'):
            if member.get('kind') not in {'function','friend'}: continue
            location = member.find('location')
            if location is None or not location.get('file'): continue
            source = location.get('file')
            if not source.startswith('library/') or not (ROOT/source).is_file():
                raise SystemExit(f'Unexpected reference source: {source}')
            parameters = []
            for parameter in member.findall('param'):
                if text(parameter.find('type')) == 'void': continue
                parameters.append({'name':text(parameter.find('declname')) or text(parameter.find('defname')), 'type':text(parameter.find('type')), 'default':text(parameter.find('defval'))})
            functions[member.get('id')] = {
                'id':member.get('id'), 'name':text(member.find('name')),
                'qualified_name':text(member.find('qualifiedname')) or text(member.find('name')),
                'definition':text(member.find('definition')), 'args':text(member.find('argsstring')),
                'return_type':text(member.find('type')), 'parameters':parameters,
                'file':source, 'line':int(location.get('line','0')),
                'declaration_file':location.get('declfile',source),
                'declaration_line':int(location.get('declline',location.get('line','0'))),
                'body_file':location.get('bodyfile',source),
                'body_start':int(location.get('bodystart','0')), 'body_end':int(location.get('bodyend','0')),
                'brief':text(member.find('briefdescription')), 'protection':member.get('prot'),
                'static':member.get('static'),
                'template_parameters':[text(param.find('type')) + (' '+text(param.find('declname')) if text(param.find('declname')) else '') for param in member.findall('templateparamlist/param')],
            }
            files.add(source)
            body = location.get('bodyfile')
            if body and (ROOT/body).is_file(): files.add(body)
    return sorted(functions.values(), key=lambda item:(item['file'],item['line'],item['id'])), types, sorted(files)


def load_notes(functions, draft):
    notes = {}
    for path in sorted(NOTES.glob('*.json')):
        data = json.loads(path.read_text())
        duplicates = notes.keys() & data.keys()
        if duplicates: raise SystemExit(f'Duplicate function notes in {path.name}: {sorted(duplicates)}')
        notes.update(data)
    errors = []
    for function in functions:
        entry = notes.get(function['id'])
        if not entry:
            errors.append(f"Missing documentation: {function['qualified_name']}{function['args']} ({function['file']})")
            continue
        if not isinstance(entry.get('summary'), str) or len(entry['summary']) < 20: errors.append(f"Missing useful summary: {function['id']}")
        if not isinstance(entry.get('returns'), str) or not entry['returns'].strip(): errors.append(f"Missing return/effect description: {function['id']}")
        if not isinstance(entry.get('details', []), list) or any(not isinstance(detail, str) for detail in entry.get('details', [])):
            errors.append(f"Details must be a list of paragraphs: {function['id']}")
        if 'example' in entry and not isinstance(entry['example'], str): errors.append(f"Example must be C++ text: {function['id']}")
        expected = {parameter_key(p,i) for i,p in enumerate(function['parameters'])}
        actual = set(entry.get('parameters',{}))
        if expected != actual: errors.append(f"Parameter documentation differs for {function['qualified_name']}: expected {sorted(expected)}, found {sorted(actual)}")
        if any(not str(value).strip() for value in entry.get('parameters',{}).values()): errors.append(f"Empty parameter documentation: {function['id']}")
    unused = notes.keys() - {f['id'] for f in functions}
    if unused: errors.append(f'Notes for absent functions: {sorted(unused)}')
    if errors and not draft: raise SystemExit('\n'.join(errors[:50])+f'\n{len(errors)} function documentation errors')
    return notes, errors


def source_binding(files, refresh, draft):
    current = {path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files}
    if refresh:
        BINDING.write_text(json.dumps(current,indent=2)+'\n')
    elif not draft:
        if not BINDING.exists(): raise SystemExit('Missing function documentation source binding; review the notes and refresh it.')
        expected = json.loads(BINDING.read_text())
        changed = sorted(path for path in expected.keys() | current.keys() if expected.get(path) != current.get(path))
        if changed: raise SystemExit('Review function documentation after source changes, then refresh the binding:\n'+'\n'.join(changed))
    return current


def anchor(function): return 'function-'+function['id']


def fence(value, language='cpp', indent=''):
    # Four backticks keep source comments containing triple fences harmless.
    return '\n'+indent+'````'+language+'\n'+'\n'.join(indent+line for line in value.splitlines())+'\n'+indent+'````\n'


def cell(value): return value.replace('|','\\|').replace('\n',' ')


def inline_code(value):
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', html.escape(value))


def source_url(revision, path, line=0):
    return f'https://github.com/wajidmanzoor/graphMine/blob/{revision}/{path}'+(f'#L{line}' if line else '')


def write_pages(functions, types, notes, revision, draft):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    by_file = defaultdict(list)
    for function in functions: by_file[display_file(function)].append(function)
    by_type = defaultdict(list)
    for kind in types: by_type[kind['file']].append(kind)
    owners = {kind['name'] for kind in types}
    overloads = defaultdict(int)
    for function in functions: overloads[function['qualified_name']] += 1

    def function_label(function):
        qualified = function['qualified_name']
        owner = qualified.rsplit('::',1)[0] if '::' in qualified else ''
        label = owner.rsplit('::',1)[-1]+'::'+function['name'] if owner in owners else function['name']
        if overloads[qualified] > 1:
            label += '('+', '.join(p['type'] for p in function['parameters'])+')'
        return clean_name(label)

    navigation = []
    for group in GROUPS:
        children = []
        for path, entries in sorted(by_file.items()):
            if group_for(path) != group: continue
            page_slug = slug(path)
            children.append({Path(path).name:f'library/api/{page_slug}.md'})
            lines = ['---','native_reference: true',f'title: "{path.removeprefix("library/")}"','---','',f'# {Path(path).name}', '', f'Read the contracts and implementations of the {len(entries)} functions declared in `{path}`.', '', f'[All functions](index.md) · [Browse by file](files.md) · [Complete source]({source_url(revision,path)})', '']
            for function in entries:
                entry = notes.get(function['id'],{})
                title = function_label(function)
                lines += ['', '<section class="native-function" markdown="1">', '', f'## `{title}` {{ #{anchor(function)} }}', '', entry.get('summary',function['brief'] or 'Documentation is being reviewed.'), '']
                qualified = clean_name(function['qualified_name'])
                signature = clean_name(function['definition']+function['args'])
                if function['template_parameters']:
                    signature = 'template <'+', '.join(function['template_parameters'])+'>\n'+signature
                local = 'anonymous_namespace{' in function['qualified_name']
                lines += [f'`{qualified}` · {group}'+(' · file-local helper' if local else ' · private helper' if function['protection']=='private' else ''), fence(signature)]
                if function['parameters']:
                    lines += ['<h3>Parameters</h3>', '', '| Parameter | Meaning |', '| --- | --- |']
                    for i, parameter in enumerate(function['parameters']):
                        key=parameter_key(parameter,i); meaning=entry.get('parameters',{}).get(key,'Documentation is being reviewed.')
                        default=f' Default: `{parameter["default"]}`.' if parameter['default'] else ''
                        label=parameter['name'] or f'Argument {i+1}'
                        lines.append(f'| `{cell(label)}`<br>`{cell(parameter["type"])}` | {cell(meaning)}{cell(default)} |')
                else:
                    lines += ['**Parameters:** none.']
                lines += ['', '<h3>Return value and effects</h3>', '', entry.get('returns','Documentation is being reviewed.'), '']
                for detail in entry.get('details',[]): lines += [detail,'']
                if entry.get('example'): lines += ['<h3>Example</h3>',fence(entry['example'])]
                body_path = function['body_file']; start=function['body_start']; end=function['body_end']
                source_path = body_path if start>0 else function['file']; source_line = start if start>0 else function['line']
                lines += [f'[Read in source]({source_url(revision,source_path,source_line)})', '']
                if start>0 and end>=start and (ROOT/body_path).is_file():
                    body='\n'.join((ROOT/body_path).read_text().splitlines()[start-1:end])
                    lines += ['??? info "Implementation"',fence(body,indent='    ')]
                lines += ['</section>','']
            if by_type[path]:
                lines += ['## Types in this file','']
                for kind in sorted(by_type[path],key=lambda item:item['name']):
                    lines += [f'<h3><code>{html.escape(clean_name(kind["name"]))}</code></h3>', '', kind['description'], '']
                    if kind['fields']:
                        described = any(field['description'] for field in kind['fields'])
                        lines += ['| Member | Type |'+(' Description |' if described else ''),'| --- | --- |'+(' --- |' if described else '')]
                        for field in kind['fields']:
                            lines.append(f'| `{cell(field["name"])}` | `{cell(field["type"])}` |'+(f' {cell(field["description"])} |' if described else ''))
                        lines += ['']
            (OUTPUT/f'{page_slug}.md').write_text('\n'.join(lines).rstrip()+'\n')
        if children: navigation.append({group:children})
    (OUTPUT/'navigation.json').write_text(json.dumps(navigation,indent=2)+'\n')
    file_lines=['---','native_reference: true','---','','# Reference by source file','','Find a module, then read the contracts of its functions and types.','','[Search all functions](index.md) · [C++ usage guide](../cpp-api.md)','']
    for group in navigation:
        for name, pages in group.items():
            file_lines += [f'## {name}','']
            for item in pages:
                for label,path in item.items(): file_lines.append(f'- [`{label}`]({Path(path).name})')
            file_lines += ['']
    (OUTPUT/'files.md').write_text('\n'.join(file_lines)+'\n')
    index=['---','native_reference: true','---','','# C++ and CUDA function reference','',f'Find the purpose, parameters, return values, and implementation of all **{len(functions)} named functions** extracted from the current GraphMine headers, runtime, graph core, and native adapters.','', 'Start with the [C++ and C API guide](../cpp-api.md) to call the runtime. Use this reference when you need a particular function or implementation detail. Public entry points and internal helpers are labelled separately. [Browse by source file](files.md).','', 'Each entry is checked against the current declarations and has a written contract. Optional backend behavior is described where builds differ. Vendored research projects are separate [research references](../../problem/research.md).','', '<div class="native-filter">','<label for="native-function-search">Find a function<input id="native-function-search" type="search" placeholder="Name, parameter, behavior, or source file" autocomplete="off"></label>','<label for="native-function-group">Section<select id="native-function-group"><option value="">All sections</option>']
    index += [f'<option value="{group}">{group}</option>' for group in GROUPS]
    index += ['</select></label></div>', '<p id="native-index-status" class="native-index-status" role="status" aria-live="polite"></p>', '<ul class="native-index" data-native-index>']
    for function in sorted(functions,key=lambda f:(f['name'].lower(),f['qualified_name'],f['file'])):
        entry=notes.get(function['id'],{}); summary=entry.get('summary',function['brief'] or 'Documentation is being reviewed.')
        path=display_file(function); group=group_for(path); qualified=clean_name(function['qualified_name'])
        searchable=' '.join([qualified,function['args'],function['file'],path,summary]).lower()
        href=f'{slug(path)}/#{anchor(function)}'
        index.append(f'<li data-function="{html.escape(searchable,quote=True)}" data-group="{group}"><a href="{href}">{html.escape(qualified)}</a><p>{inline_code(summary)}</p><small>{html.escape(path)} · {group}</small></li>')
    index += ['</ul>','<button type="button" id="native-show-more" class="native-show-more">Show more functions</button>','']
    (OUTPUT/'index.md').write_text('\n'.join(index))
    return len(by_file)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml',required=True,type=Path)
    parser.add_argument('--draft',action='store_true',help='Local preview only; allow unfinished notes.')
    parser.add_argument('--refresh-source-binding',action='store_true')
    args=parser.parse_args()
    if args.draft and args.refresh_source_binding:
        parser.error('A draft cannot certify reviewed source; finish the notes before refreshing the binding.')
    functions,types,files=extract(args.xml)
    notes,errors=load_notes(functions,args.draft)
    binding=source_binding(files,args.refresh_source_binding,args.draft)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    page_count=write_pages(functions,types,notes,revision,args.draft)
    coverage={'functions':len(functions),'documented':sum(f['id'] in notes for f in functions),'source_files':len(binding),'function_pages':page_count,'errors':len(errors)}
    (OUTPUT/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    print(json.dumps(coverage))

if __name__=='__main__': main()
