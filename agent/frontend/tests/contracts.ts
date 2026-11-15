import type {Client} from "../types/client";
import type {components} from "../generated/api";

declare const api: Client;
const query: components["schemas"]["CypherRequest"] = {statement: "MATCH (n) RETURN n", parameters: {id: 9007199254740993n}};
api("post", "/api/database-sources/{source_id}/queries", {path: {source_id: "demo"}, body: query});
api("get", "/api/database-jobs/{identifier}", {path: {identifier: "job"}});
api("get", "/api/database-query-snapshots/{identifier}/table", {path: {identifier: "snapshot"}, query: {offset: 0, limit: 20, direction: "desc"}});
api("post", "/api/workflows/{workflow_id}/run", {path: {workflow_id: "workflow"}, body: {workflow_hash: "hash", expected_revision: 1}});
const selection: components["schemas"]["EnrichmentRequest"] = {mapping: "Account", ids: [9007199254740993n, "001", 1]};
api("post", "/api/files/{file_id}/enrichments", {path: {file_id: "input"}, body: selection});

// @ts-expect-error The route requires a source path argument.
api("post", "/api/database-sources/{source_id}/queries", {body: query});
// @ts-expect-error Query input is generated from CypherRequest, not an arbitrary map.
api("post", "/api/database-sources/{source_id}/queries", {path: {source_id: "demo"}, body: {sql: "SELECT 1"}});
// @ts-expect-error This route has no POST operation.
api("post", "/api/database-jobs/{identifier}", {path: {identifier: "job"}});
// @ts-expect-error Approval requires the exact reviewed revision.
api("post", "/api/workflows/{workflow_id}/run", {path: {workflow_id: "workflow"}, body: {workflow_hash: "hash"}});
// @ts-expect-error Boolean IDs are not graph IDs.
const invalid: components["schemas"]["EnrichmentRequest"] = {mapping: "Account", ids: [true]};
void invalid;
