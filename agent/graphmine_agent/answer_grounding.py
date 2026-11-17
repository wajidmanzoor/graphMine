"""Turn-scoped evidence and deterministic, conservative answer validation.

Factual clauses must be present in a cited tool result. This deliberately does
not pretend that matching a bag of numbers or running a name recognizer proves
a claim: swapped subjects, counts, units and negation all fail. Writers can
select {{source_id}} quotations instead of reproducing data or vertex IDs.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import re


SAFE_LEADS = frozenset({
    "Here are the results.", "Here is what the saved result shows.",
    "Here is what the sources say.",
})
SLOT = re.compile(r"\{\{([^{}]+)\}\}")


def normalized(text):
    return " ".join(text.split()).strip().rstrip(".")


def sentences(text):
    # Do not split decimal numbers, abbreviations inside tokens or typed names.
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\d\"'“])|\n+", text) if part.strip()]


@dataclass
class Evidence:
    turn_id: str
    sources: dict = field(default_factory=dict)

    def record(self, tool, rows):
        """Called with actual tool results, never with the model's citations."""
        for source in rows:
            row = deepcopy(source)
            if row['kind'] not in {'fact', 'contract', 'doc', 'web'} or not row.get('text'):
                raise ValueError('An evidence source needs a supported kind and text.')
            row.update(turn_id=self.turn_id, tool=tool)
            if row['id'] in self.sources and self.sources[row['id']] != row:
                raise ValueError('A source ID cannot identify two results in the same turn.')
            self.sources[row['id']] = row
        return self

    def citation(self, identifier):
        return {key: self.sources[identifier][key] for key in ('id', 'kind', 'ref')}

    def subset(self, identifiers):
        return Evidence(self.turn_id, {key: deepcopy(self.sources[key]) for key in dict.fromkeys(identifiers)})

    def answer(self, text, identifiers):
        return {'text': text, 'citations': [self.citation(key) for key in dict.fromkeys(identifiers)]}

    def facts(self, identifiers=None):
        identifiers = list(self.sources) if identifiers is None else identifiers
        rows = [self.sources[key] for key in dict.fromkeys(identifiers)]
        return self.answer('\n'.join(row['text'] for row in rows), [row['id'] for row in rows])

    def public_sources(self, identifiers):
        return [deepcopy(self.sources[key]) for key in dict.fromkeys(identifiers)]

    def render(self, answer, *, data_answer=False):
        """Expand only citations selected from this turn's real tool results."""
        identifiers = {row['id'] for row in answer.get('citations', [])}
        text = answer.get('text', '')
        if data_answer:
            # Literal data stays in code. The writer selects quotations and can
            # add a neutral introduction; it never emits a vertex ID list.
            remainder = SLOT.sub('', text).strip()
            if remainder and remainder not in SAFE_LEADS:
                raise ValueError('Use source placeholders for data claims; do not rewrite data or IDs.')
        def expand(match):
            key = match[1]
            if key not in identifiers or key not in self.sources:
                raise ValueError('A quoted source must have a current-turn citation.')
            return self.sources[key]['text']
        if data_answer:
            # A fact may begin in lowercase. Keep code-rendered statements on
            # separate lines so an introduction cannot merge into its claim.
            parts = ([remainder] if remainder else []) + [expand(match) for match in SLOT.finditer(text)]
            return {**answer, 'text': '\n'.join(parts).strip()}
        return {**answer, 'text': SLOT.sub(expand, text).strip()}

    def check(self, answer, *, turn_id, data_answer=False):
        errors = []
        if turn_id != self.turn_id:
            return ['Evidence belongs to another turn.']
        if not isinstance(answer, dict) or not isinstance(answer.get('text'), str):
            return ['An answer needs text and citations.']
        citations = answer.get('citations')
        if not isinstance(citations, list) or not citations:
            return ['An answer needs citations from this turn.']
        selected = []
        for citation in citations:
            identifier = citation.get('id') if isinstance(citation, dict) else None
            source = self.sources.get(identifier) if isinstance(identifier, str) else None
            if not source or source.get('turn_id') != turn_id or citation != self.citation(source['id']):
                errors.append('A citation was not returned by a tool in this turn.')
            elif data_answer and source['kind'] == 'web':
                errors.append('Data answers cannot cite the web.')
            else:
                selected.append(source)
        if errors:
            return list(dict.fromkeys(errors))
        text = answer['text'].strip()
        if not text:
            return ['The answer is empty.']
        claims = sentences(text)
        allowed = {normalized(part) for source in selected for part in sentences(source['text'])}
        # Accept whole recorded paragraphs as well as their complete sentences.
        allowed.update(normalized(source['text']) for source in selected)
        for claim in claims:
            if claim in SAFE_LEADS:
                continue
            if normalized(claim) not in allowed:
                errors.append('A factual sentence does not match its cited source: ' + claim[:180])
        if all(claim in SAFE_LEADS for claim in claims):
            errors.append('The reply does not contain a sourced finding.')
        # Web text is quoted, not represented as checked graph data. Bound the
        # extractive quote per source; local facts/contracts have no such limit.
        for source in selected:
            if source['kind'] == 'web':
                quoted = sum(len(claim.split()) for claim in claims if normalized(claim) in
                             {normalized(part) for part in sentences(source['text'])})
                if quoted > 25:
                    errors.append('Web quotations are limited to 25 words per source.')
        return list(dict.fromkeys(errors))


def fact_sources(facts, *, workflow_id, revision):
    return [{'id': fact['id'], 'kind': 'fact', 'ref': f"workflow:{workflow_id}:revision:{revision}:step:{fact.get('step', 'answer')}:{fact['id']}",
             'title': fact.get('operation_title', 'Result fact'), 'text': fact.get('text', fact['statement'])} for fact in facts]


def answer_schema(evidence, *, data_answer=False):
    # The public reply has citation triples. The writer only picks opaque IDs;
    # code fills the kind and reference from the current tool-result registry.
    text = {'type': 'string', 'minLength': 1, 'maxLength': 6000}
    if data_answer:
        # Constrain generation too: data writers cannot emit literal vertex IDs
        # or data claims even in a draft. Cross-field citation binding is checked
        # by code after the grammar has enforced the permitted vocabulary.
        leads = '|'.join(re.escape(lead).replace(r'\ ', ' ') for lead in sorted(SAFE_LEADS))
        identifiers = '|'.join(re.escape(key) for key in evidence.sources)
        text['pattern'] = r'^(?:(?:' + leads + r')\s*)?(?:\{\{(?:' + identifiers + r')\}\}\s*){1,6}$'
    return {'type': 'object', 'additionalProperties': False, 'required': ['text', 'source_ids'],
            'properties': {'text': text,
                           'source_ids': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'uniqueItems': True,
                                          'items': {'enum': list(evidence.sources)}}}}
