"""Transactional, lightweight dataset summaries and artifact change tokens."""


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS dataset_summaries (
          id TEXT PRIMARY KEY REFERENCES dataset_versions(id) ON DELETE CASCADE,
          owner_id TEXT, dataset_id TEXT NOT NULL, version INTEGER NOT NULL,
          sequence INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
          metadata TEXT NOT NULL, token TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS dataset_summaries_owner ON dataset_summaries(owner_id,sequence DESC);
        CREATE INDEX IF NOT EXISTS dataset_summaries_collection ON dataset_summaries(owner_id,dataset_id,version DESC);
        CREATE INDEX IF NOT EXISTS dataset_summaries_kind ON dataset_summaries(owner_id,kind,sequence DESC);
        CREATE TABLE IF NOT EXISTS preview_blob_revisions (
          owner_id TEXT NOT NULL, sha256 TEXT NOT NULL, token TEXT NOT NULL,
          PRIMARY KEY(owner_id,sha256),
          FOREIGN KEY(owner_id,sha256) REFERENCES query_preview_blobs(owner_id,sha256) ON DELETE CASCADE
        );
        CREATE TRIGGER IF NOT EXISTS dataset_summary_insert AFTER INSERT ON dataset_versions BEGIN
          INSERT INTO dataset_summaries VALUES (new.id,new.owner_id,new.dataset_id,new.version,new.rowid,
            json_extract(new.metadata,'$.name'),json_extract(new.metadata,'$.kind'),json_remove(new.metadata,'$.source'),hex(randomblob(16)));
        END;
        CREATE TRIGGER IF NOT EXISTS dataset_summary_update AFTER UPDATE ON dataset_versions BEGIN
          UPDATE dataset_summaries SET owner_id=new.owner_id,dataset_id=new.dataset_id,version=new.version,sequence=new.rowid,
            name=json_extract(new.metadata,'$.name'),kind=json_extract(new.metadata,'$.kind'),
            metadata=json_remove(new.metadata,'$.source'),token=hex(randomblob(16)) WHERE id=old.id;
        END;
        CREATE TRIGGER IF NOT EXISTS preview_revision_insert AFTER INSERT ON query_preview_blobs BEGIN
          INSERT INTO preview_blob_revisions VALUES (new.owner_id,new.sha256,hex(randomblob(16)));
        END;
        CREATE TRIGGER IF NOT EXISTS preview_revision_update AFTER UPDATE ON query_preview_blobs BEGIN
          UPDATE preview_blob_revisions SET token=hex(randomblob(16)) WHERE owner_id=new.owner_id AND sha256=new.sha256;
        END;
        INSERT INTO dataset_summaries SELECT v.id,v.owner_id,v.dataset_id,v.version,v.rowid,
          json_extract(v.metadata,'$.name'),json_extract(v.metadata,'$.kind'),json_remove(v.metadata,'$.source'),hex(randomblob(16))
          FROM dataset_versions v WHERE NOT EXISTS (SELECT 1 FROM dataset_summaries s WHERE s.id=v.id);
        INSERT INTO preview_blob_revisions SELECT b.owner_id,b.sha256,hex(randomblob(16)) FROM query_preview_blobs b
          WHERE NOT EXISTS (SELECT 1 FROM preview_blob_revisions r WHERE r.owner_id=b.owner_id AND r.sha256=b.sha256);
    """)
