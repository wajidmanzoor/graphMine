# Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
# Copied: 2026-11-15T22:51:58+00:00
# Published code block: 2

#!/usr/bin/env bash
#
# Bulk-import the LDBC SNB BI SF100 initial snapshot into the Neo4j database "snb100".
#
# Usage:
#   MODE=offline ./import_snb100.sh   # stop Neo4j during the import; the importer gets the
#                                     # whole machine and runs much faster
#   MODE=online  ./import_snb100.sh   # keep the other databases online; the importer runs
#                                     # with a capped memory budget and takes far longer
#   SCHEMA_FILE= ./import_snb100.sh   # skip building indices during the import
#
# Only the target database is ever touched. This host's data directory also holds several
# unrelated benchmark databases and the "system" registry, so the databases directory is
# never cleared as a whole.

set -euo pipefail

# ----- Configuration ---------------------------------------------------------
DB_NAME=snb100
CSV_DIR=/datasets/prop_datasets/ldbc_100/csv
HEADER_DIR=/datasets/prop_datasets/ldbc_snb_bi/neo4j/headers
BOLT=bolt://localhost:7689
OUT_DIR=/datasets/prop_datasets/ldbc_100/scripts
TIMING_FILE=${OUT_DIR}/import-timing.tsv

# The importer runs as the "neo4j" user and cannot write into scripts/ (owned by exouser,
# mode 775). Its own outputs -- temporary files and the bad-entries report -- therefore go
# to a directory it owns on local disk, which is also faster than NFS.
WORK_DIR=/media/volume/sdb/neo4j-import
TEMP_PATH=${WORK_DIR}/tmp
REPORT_FILE=${WORK_DIR}/import-report.txt

# Indices and constraints are built during the import rather than afterwards: populating
# the Message(id) uniqueness constraint over 249.5 million nodes as a separate pass would
SCHEMA_FILE=${SCHEMA_FILE-${OUT_DIR}/indices.cypher}

MODE=${MODE:-online}
if [[ "${MODE}" == "offline" ]]; then
    # The off-heap cap cannot be sized against the whole machine: the importer's JVM heap
    # (10g, from server.memory.heap.max_size in neo4j.conf) sits on top of it, plus roughly
    # 5g for the id mapper and other structures. A 40g cap drove anon-rss to 52.5 GiB during
    # the relationship phase and systemd-oomd killed the process on this 58 GiB host.
    # 24g + 10g heap + overhead is about 40g, leaving 18g of headroom.
    MAX_OFF_HEAP=24g
    THREADS=16
else
    # The running server already holds 10g of heap and 16g of page cache
    MAX_OFF_HEAP=8g
    THREADS=14                                     # leave 2 of 16 cores to the server
fi

# The system default JVM is Java 17; neo4j-admin needs 21. The importer's own heap comes
# from neo4j.conf -- the 2026.05.0 NeoAdminBoot launcher no longer reads HEAP_SIZE -- so
# --max-off-heap-memory below is the only memory knob available here. It covers the page
# cache and the id-mapping structures.
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# The safety net that matters for an unattended run: whatever makes this script exit -- an
# OOM during the import, a full disk, a bad argument, a failed preflight -- the Neo4j service
# must come back. On the previous attempt set -e terminated the script at the import and the
# systemctl start at the end never ran, leaving nine other databases offline for an hour.
restore_service () {
    local rc=$?
    if [[ "${MODE}" == "offline" ]] && ! systemctl is-active --quiet neo4j; then
        echo "== Exit code ${rc}: restoring the Neo4j service =="
        sudo systemctl start neo4j || true
    fi
    if [[ ${rc} -ne 0 ]]; then
        echo "== Script exited with code ${rc} (import did not complete) =="
    fi
    return ${rc}
}
trap restore_service EXIT

# ----- Guard rail -------------------------------------------------------------
if [[ -z "${DB_NAME}" || "${DB_NAME}" == "system" || "${DB_NAME}" == "neo4j" ]]; then
    echo "Refusing to run: DB_NAME is empty or points at system/neo4j." >&2
    exit 1
fi

echo "== Configuration =="
echo "  database    ${DB_NAME}"
echo "  mode        ${MODE}"
echo "  off-heap    ${MAX_OFF_HEAP}   threads ${THREADS}"
echo "  CSV         ${CSV_DIR}"
echo "  headers     ${HEADER_DIR}"
echo "  temp dir    ${TEMP_PATH}"
echo "  schema      ${SCHEMA_FILE:-(skipped)}"

# ----- Preflight: all 31 entity directories present and non-empty -------------
echo "== Checking data directories =="
missing=0
for sub in static dynamic; do
    while read -r h; do
        entity=$(basename "${h}" .csv)
        d="${CSV_DIR}/initial_snapshot/${sub}/${entity}"
        if [[ ! -d "${d}" ]]; then
            echo "  missing directory: ${d}" >&2; missing=1
        elif ! find "${d}" -maxdepth 1 -name 'part-*.csv*' -type f -print -quit | grep -q .; then
            echo "  no part files: ${d}" >&2; missing=1
        fi
    done < <(find "${HEADER_DIR}/${sub}" -name '*.csv')
done
[[ ${missing} -eq 0 ]] || { echo "Preflight failed, aborting." >&2; exit 1; }
echo "  all 31 entity directories present"

# ----- Take the target database offline and drop it (repeatable) --------------
# Drop and re-create rather than overwrite in place: dropping also clears the database's
# transaction logs and its system-database entry, so no stale metadata survives.
if cypher-shell -a "${BOLT}" -d system "RETURN 1" >/dev/null 2>&1; then
    echo "== Stopping and dropping ${DB_NAME} (other databases unaffected) =="
    cypher-shell -a "${BOLT}" -d system "STOP DATABASE ${DB_NAME} IF EXISTS WAIT" || true
    cypher-shell -a "${BOLT}" -d system "DROP DATABASE ${DB_NAME} IF EXISTS WAIT"
    cypher-shell -a "${BOLT}" -d system "SHOW DATABASES YIELD name, currentStatus"
else
    echo "== Server not running, skipping STOP/DROP (re-run case) =="
fi

# Clear any temporary files left by a previous run. The cleanup at the end of this script
# does not run if the process is killed (an OOM, for instance), and the leftover temp-<db>
# directory can be tens of gigabytes.
sudo rm -rf "${TEMP_PATH}"
# The directory must be owned by neo4j or the importer cannot write into it
sudo mkdir -p "${TEMP_PATH}"
sudo chown -R neo4j:neo4j "${WORK_DIR}"
if ! sudo -u neo4j touch "${WORK_DIR}/.probe" 2>/dev/null; then
    echo "Preflight failed: the neo4j user cannot write to ${WORK_DIR}" >&2; exit 1
fi
sudo -u neo4j rm -f "${WORK_DIR}/.probe"
echo "  neo4j can write to ${WORK_DIR}"

if [[ -n "${SCHEMA_FILE}" ]] && ! sudo -u neo4j test -r "${SCHEMA_FILE}"; then
    echo "Preflight failed: the neo4j user cannot read ${SCHEMA_FILE}" >&2
    exit 1
fi

if [[ "${MODE}" == "offline" ]]; then
    if systemctl is-active --quiet neo4j; then
        echo "== MODE=offline: stopping Neo4j (data untouched, restarted afterwards) =="
        sudo systemctl stop neo4j
    else
        echo "== Server already stopped =="
    fi
fi

# ----- Assemble the --nodes / --relationships arguments -----------------------
PART='part-*.csv*'
args=()
declare -A GROUP_BYTES=()      # input bytes per group, for throughput afterwards
add_nodes () {   # $1=labels  $2=static|dynamic  $3=entity
    args+=( "--nodes=$1=${HEADER_DIR}/$2/$3.csv$(find "${CSV_DIR}/initial_snapshot/$2/$3" -type f -name "${PART}" -printf ',%p')" )
    GROUP_BYTES["node/$1/$3"]=$(find "${CSV_DIR}/initial_snapshot/$2/$3" -type f -name "${PART}" -printf '%s\n' | awk '{s+=$1} END{print s+0}')
}
add_rels () {    # $1=RELTYPE  $2=static|dynamic  $3=entity
    args+=( "--relationships=$1=${HEADER_DIR}/$2/$3.csv$(find "${CSV_DIR}/initial_snapshot/$2/$3" -type f -name "${PART}" -printf ',%p')" )
    GROUP_BYTES["rel/$1/$3"]=$(find "${CSV_DIR}/initial_snapshot/$2/$3" -type f -name "${PART}" -printf '%s\n' | awk '{s+=$1} END{print s+0}')
}

# Eight node groups. Comment and Post both carry the Message label, which is what lets
# the queries match (:Message) across the two. The Place and Organisation headers end in a
# :LABEL column, so a city arrives as (:Place:City), a university as (:Organisation:University).
add_nodes Place            static  Place
add_nodes Organisation     static  Organisation
add_nodes TagClass         static  TagClass
add_nodes Tag              static  Tag
add_nodes Forum            dynamic Forum
add_nodes Person           dynamic Person
add_nodes Message:Comment  dynamic Comment      # Comment and Post both get :Message
add_nodes Message:Post     dynamic Post

# Twenty-three relationship groups, collapsing into eleven relationship types
add_rels IS_PART_OF      static  Place_isPartOf_Place
add_rels IS_SUBCLASS_OF  static  TagClass_isSubclassOf_TagClass
add_rels IS_LOCATED_IN   static  Organisation_isLocatedIn_Place
add_rels HAS_TYPE        static  Tag_hasType_TagClass
add_rels HAS_CREATOR     dynamic Comment_hasCreator_Person
add_rels IS_LOCATED_IN   dynamic Comment_isLocatedIn_Country
add_rels REPLY_OF        dynamic Comment_replyOf_Comment
add_rels REPLY_OF        dynamic Comment_replyOf_Post
add_rels CONTAINER_OF    dynamic Forum_containerOf_Post
add_rels HAS_MEMBER      dynamic Forum_hasMember_Person
add_rels HAS_MODERATOR   dynamic Forum_hasModerator_Person
add_rels HAS_TAG         dynamic Forum_hasTag_Tag
add_rels HAS_INTEREST    dynamic Person_hasInterest_Tag
add_rels IS_LOCATED_IN   dynamic Person_isLocatedIn_City
add_rels KNOWS           dynamic Person_knows_Person
add_rels LIKES           dynamic Person_likes_Comment
add_rels LIKES           dynamic Person_likes_Post
add_rels HAS_CREATOR     dynamic Post_hasCreator_Person
add_rels HAS_TAG         dynamic Comment_hasTag_Tag
add_rels HAS_TAG         dynamic Post_hasTag_Tag
add_rels IS_LOCATED_IN   dynamic Post_isLocatedIn_Country
add_rels STUDY_AT        dynamic Person_studyAt_University
add_rels WORK_AT         dynamic Person_workAt_Company

echo "== Argument groups: ${#args[@]} (expected 8 nodes + 23 relationships = 31) =="

# Persist the per-group input sizes so throughput can be derived later
{ echo -e "group\tbytes"; for k in "${!GROUP_BYTES[@]}"; do echo -e "${k}\t${GROUP_BYTES[$k]}"; done | sort; } > "${OUT_DIR}/import-input-bytes.tsv"

# ----- Import -----------------------------------------------------------------
# Argument order matters: ${DB_NAME} must precede --nodes/--relationships, which are
# declared variadic (<files>...) and would swallow a trailing database name as one more
# data file, failing with "NoSuchFileException: snb100".
# --id-type=INTEGER  integer ids map far more cheaply than strings over 254.6M nodes
echo "== Starting the import; expect hours (source and target both on NFS) =="
T0=$(date +%s); date
sudo -u neo4j --preserve-env=JAVA_HOME \
    neo4j-admin database import full \
    "${DB_NAME}" \
    --id-type=INTEGER \
    --ignore-empty-strings=true \
    --bad-tolerance=0 \
    --delimiter='|' \
    --array-delimiter=';' \
    --threads="${THREADS}" \
    --max-off-heap-memory="${MAX_OFF_HEAP}" \
    --temp-path="${TEMP_PATH}" \
    --report-file="${REPORT_FILE}" \
    ${SCHEMA_FILE:+--schema="${SCHEMA_FILE}"} \
    --overwrite-destination \
    --verbose \
    "${args[@]}"
T1=$(date +%s); date
echo "== Import finished in $(( (T1-T0)/3600 ))h $(( (T1-T0)%3600/60 ))m $(( (T1-T0)%60 ))s =="
# The report is written by neo4j on local disk; copy it back for convenience
sudo cp "${REPORT_FILE}" "${OUT_DIR}/import-report.txt" 2>/dev/null && sudo chown exouser:exouser "${OUT_DIR}/import-report.txt" || true

echo -e "phase\tseconds" > "${TIMING_FILE}"
echo -e "total_wall_clock\t$((T1-T0))" >> "${TIMING_FILE}"

if [[ "${MODE}" == "offline" ]]; then
    echo "== Restarting Neo4j =="
    sudo systemctl start neo4j
    for i in $(seq 1 120); do
        cypher-shell -a "${BOLT}" -d system "RETURN 1" >/dev/null 2>&1 && break
        sleep 5
    done
fi

# ----- Register the store as a database and bring it online -------------------
echo "== Creating and starting ${DB_NAME} =="
T2=$(date +%s)
cypher-shell -a "${BOLT}" -d system "CREATE DATABASE ${DB_NAME} WAIT"
T3=$(date +%s)
echo -e "create_database_online\t$((T3-T2))" >> "${TIMING_FILE}"
cypher-shell -a "${BOLT}" -d system "SHOW DATABASES YIELD name, currentStatus"

# ----- Verify -----------------------------------------------------------------
echo "== Node count per label =="
cypher-shell -a "${BOLT}" -d "${DB_NAME}" \
    "MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS cnt ORDER BY cnt DESC" \
    | tee "${OUT_DIR}/count-nodes.txt"

echo "== Relationship count per type =="
cypher-shell -a "${BOLT}" -d "${DB_NAME}" \
    "MATCH ()-[r]->() RETURN type(r) AS relType, count(*) AS cnt ORDER BY cnt DESC" \
    | tee "${OUT_DIR}/count-rels.txt"

echo "== Index and constraint state =="
cypher-shell -a "${BOLT}" -d "${DB_NAME}" "SHOW INDEXES YIELD name, state, owningConstraint"

sudo rm -rf "${TEMP_PATH}" 2>/dev/null || true
echo
echo "Done. Output files:"
echo "  ${OUT_DIR}/import-report.txt        importer bad-entries report"
echo "  ${TIMING_FILE}                  timings"
echo "  ${OUT_DIR}/import-input-bytes.tsv  input bytes per group"
echo "  ${OUT_DIR}/count-nodes.txt         node count per label"
echo "  ${OUT_DIR}/count-rels.txt          relationship count per type"