# What the language model does

Know which parts of an answer involve language interpretation and which come from computation.

The model interprets the question in context, proposes a supported problem and operation, helps phrase a clarification, and explains computed results. It receives bounded descriptions of the selected input and available operations rather than unlimited access to every possible analysis.

The application does not accept model-generated numbers as algorithm outputs. It does not execute arbitrary generated analysis code or chart code. A proposed operation must pass input and parameter checks, and returned facts constrain the explanation.

This boundary is useful because fluent text can hide an incorrect assumption. For example, “most connected” can mean degree, a centrality score, or membership in a dense group. Asking which meaning you intend is better than silently treating them as equivalent.

The model can still misunderstand a request. Inspect the **Family**, **Problem**, **Operation**, and quality shown in a choice. Use clarification or edit the parameters when the proposed computation does not answer your question.
