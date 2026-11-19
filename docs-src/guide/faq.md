# Troubleshooting and glossary

Resolve common problems and learn the terms used in the app and catalog.

## Common problems

**The model is busy.** Wait and retry rather than sending the same question repeatedly. Check **Activity** and your allowance in **Settings › Account**. Contact the person who gave you access if it persists.

**The calculation failed.** Open **Details**. Check the selected input, required parameters, graph direction, weights, and partitions. A GPU preference does not make an incompatible input valid. Correct the stated issue before retrying.

**The result is incomplete.** Read the collection and computation status separately. A complete count may accompany a bounded list. A graph preview may also be capped independently. Do not treat a displayed subset as an exhaustive result.

**My view did not save.** Use **Retry saving**. If the app reports conflicting changes, choose **Reload saved view** or **Keep this view** before closing the tab.

**I cannot sign in.** Check the account details you were given and contact the person who provided access. The app does not offer public self-registration.

**Two choices sound similar.** Compare their formal problem, operation, parameters, and guarantee. “Maximal” means unextendable; “maximum” means largest. An exact operation is not a different approximate method merely because it is given a different label.

**The answer and graph show different counts.** The graph may be a preview, a selected item, or a filtered view. Read the input scope, total count, materialized count, and display limit in the result context.

## Glossary

| Term | Meaning |
| --- | --- |
| Family | A broad group of related graph questions. |
| Formal problem | A precise input, objective, output, and guarantee contract. |
| Operation | A callable calculation implementing a supported problem profile. |
| Backend | A compiled implementation used by an operation. |
| Exact | A completed result satisfies the selected exact contract. |
| Heuristic | A method supplies a candidate without an automatic global-optimum promise. |
| Learned | A prediction or representation produced by a model. |
| Witness | A concrete object supporting an answer, such as a clique, path, or cut. |
| Provenance | The recorded input, parameters, implementation, and transformations behind a result. |
| Snapshot | The fixed input or result version used or saved at a particular point. |
| Materialization | Returning the actual items, rather than only their count or objective value. |
| Complete | Exhaustive or finished for the particular computation or collection described. |
| Maximal | Cannot be extended while retaining the required property. |
| Maximum | Has the greatest possible objective value under the contract. |
