# From a question to an answer

Follow the decisions and checks made for one analysis.

```mermaid
sequenceDiagram
  actor U as You
  participant A as GraphMine
  participant M as Language model
  participant L as Graph library
  U->>A: Question and selected input
  A->>M: Question with bounded data context
  M-->>A: Family, formal problem, calculation
  opt Meaning or parameters are unclear
    A-->>U: Clarification or choice cards
    U->>A: Confirm the intended question
  end
  A->>L: Check input and parameters
  L-->>A: Valid request or specific error
  opt Expert mode
    A-->>U: Plan for review
    U->>A: Approve the plan
  end
  A->>L: Compute with a compatible implementation
  L-->>A: Checked result, status, and provenance
  A->>M: Computed facts for explanation
  M-->>A: Proposed explanation
  A->>A: Check grounding and select views
  A-->>U: Answer, evidence, and result views
```

The model proposes an interpretation within the known catalog. It cannot create a new executable algorithm to fill a gap. The runtime checks actual inputs and parameters, including derived inputs in multi-step work. A proposed plan is not proof that an operation can run.

Normal mode proceeds after the necessary user choices. Expert mode exposes the plan for review and approval. Both use the same native contracts and result checks.

When execution fails, the answer is a failure with a reason. When a collection is incomplete, that status travels with it. An explanation must stay within the returned facts; if generated wording cannot pass grounding checks, the application can show a factual fallback.
