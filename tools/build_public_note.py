#!/usr/bin/env python3
"""Build a public reading edition without copying the old internal PDF."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph
ROOT=Path(__file__).resolve().parents[1]
output=ROOT/'docs-src/research-note/graphmine.pdf'
output.parent.mkdir(parents=True,exist_ok=True)
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='NoteTitle',fontName='Helvetica-Bold',fontSize=23,leading=28,textColor=colors.HexColor('#01411c'),spaceAfter=14))
styles['BodyText'].fontSize=10.5;styles['BodyText'].leading=15;styles['BodyText'].spaceAfter=10
sections=[
('GraphMine: from questions to checked graph computations','Public technical note. GraphMine contributors. Public reading edition, November 19, 2026.'),
('Abstract','GraphMine turns questions about connected records into explicit graph computations. A language model helps interpret the question and select a formal topic. A compiled C++/CUDA runtime checks the input and parameters, executes a supported algorithm, and returns structured results. The application uses those facts to construct explanations and views. A shared taxonomy distinguishes topic families, formal contracts, callable problems, and implementation profiles. Quality, completeness, and provenance remain visible so that a candidate solution, a bounded collection, and a proven optimum are not confused.'),
('1. The question is part of the computation','A request to find a dense group can refer to a maximum clique, a densest subgraph, or a fixed-size dense subgraph. These objectives need not select the same vertices. Direction, edge weights, vertex identity, and bipartite sides also affect the meaning of a result. A correct implementation cannot repair an incorrectly chosen question.'),
('2. Families, formal topics, and problems','Families organize related goals. A formal topic contract declares inputs, normalization, parameters, required outputs, solution semantics, validation rules, and edge cases. An problem supplies a callable implementation profile. Its compiled backends may differ in input support and quality. The public catalog is generated from the authoritative contracts and a source-bound native build snapshot. Research references are listed separately from executable implementations.'),
('3. From intent to execution','The language model proposes an interpretation within the supported catalog. GraphMine asks for clarification when the meaning or a required parameter remains unclear. The library checks the actual input and problem parameters before computing. Expert mode adds explicit review of the plan. The same contracts apply regardless of the interaction mode. The model does not supply the algorithm output or write executable calculation code.'),
('4. Reading a result','An exact completed result satisfies the selected exact contract; an optimum is claimed only when required and established. A heuristic result is a candidate under its declared rules. A learned result is a prediction or representation, not ground truth. Some quality guarantees depend on parameters or the selected backend. CPU and GPU describe implementation placement, not exactness.'),
('5. Completeness and reproducibility','A complete count can accompany a bounded list of witnesses. A visualization can show a subset of a complete stored result. These are different limitations and must remain visible. A reproducible run records the input snapshot, problem, parameters, implementation, normalization, and output status. Numerical tolerances and random seeds matter when the problem uses them.'),
('6. Explanation and views','The application supplies computed facts to the language model and checks the explanation against those facts. A factual fallback is available when generated wording fails grounding checks. Views are selected from result types and structure: partitions suggest groups, bicliques have two sides, paths have order, and matrices have row and column identities. The model does not invent a chart to establish an unsupported claim.'),
('7. Evaluation and limits','Routing is evaluated separately from numerical correctness. Reference implementations and contract-specific checks test structural results; CPU/GPU comparisons must allow valid alternative witnesses and declared numerical tolerances. UI and end-to-end checks test whether a user can complete a workflow. No new numerical accuracy or performance claim is made in this reading edition. Historical results need their original scope, date, revision, and test conditions before comparison.'),
('Further reading','The public documentation contains formal definitions, runnable problem examples, current native code documentation, and topic-specific paper references. Documentation: https://wajidmanzoor.github.io/graphMine/ . Source: https://github.com/wajidmanzoor/graphMine . This is a technical note, not a peer-reviewed evaluation paper.')]
story=[]
for i,(title,body) in enumerate(sections):
 story.append(Paragraph(escape(title),styles['NoteTitle'] if i==0 else styles['Heading2']))
 story.append(Paragraph(escape(body),styles['BodyText']))
def footer(canvas,doc):
 canvas.setFont('Helvetica',8);canvas.drawString(48,28,'GraphMine · Public reading edition · November 19, 2026');canvas.drawRightString(548,28,str(doc.page))
SimpleDocTemplate(str(output),title=sections[0][0],author='GraphMine contributors',leftMargin=48,rightMargin=48,topMargin=42,bottomMargin=48).build(story,onFirstPage=footer,onLaterPages=footer)
print(output.relative_to(ROOT))
