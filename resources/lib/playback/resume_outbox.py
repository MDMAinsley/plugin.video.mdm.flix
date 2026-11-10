"""Durable MDBList delivery state, committed with the local checkpoint."""
import time
import uuid

# Keep a margin below MDBList's 80% watched boundary even if it rounds.
MAX_RESUME_PERCENT = 79.49


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='resume_outbox'").fetchone()


def replace(db, identity, sync, position, duration, watched):
    if exists(db):
        db.execute('DELETE FROM resume_outbox WHERE identity=?', (identity,))
    if not sync or watched or duration < 60 or not 0 < position <= duration * MAX_RESUME_PERCENT / 100:
        return
    sync_id, sampled, boot = sync
    db.execute('CREATE TABLE IF NOT EXISTS resume_outbox ('
               'identity TEXT PRIMARY KEY REFERENCES progress(identity) ON DELETE CASCADE, '
               'ticket TEXT NOT NULL, sync_id TEXT NOT NULL, position REAL NOT NULL, duration REAL NOT NULL, '
               'sampled REAL NOT NULL, due REAL NOT NULL, boot TEXT, failures INTEGER NOT NULL DEFAULT 0, '
               'writes INTEGER NOT NULL DEFAULT 0, sent_id INTEGER, sent_time INTEGER)')
    db.execute('INSERT INTO resume_outbox(identity,ticket,sync_id,position,duration,sampled,due,boot) '
               'VALUES(?,?,?,?,?,?,?,?)', (identity, uuid.uuid4().hex, sync_id, position, duration, sampled, time.time(), boot))


class Outbox:
    def __init__(self, store):
        self.store = store

    def pending(self, sync_id, now, boot):
        with self.store.db() as db:
            if exists(db):
                row = db.execute('SELECT o.*, p.item FROM resume_outbox o JOIN progress p USING(identity) '
                                 'WHERE o.sync_id=? AND o.due<=? AND (o.boot IS NULL OR o.boot<>?) '
                                 'ORDER BY o.due,o.sampled LIMIT 1', (sync_id, now, boot)).fetchone()
                if row:
                    return dict(row)

    def count(self, sync_id):
        with self.store.db() as db:
            if not exists(db):
                return 0
            return db.execute('SELECT count(*) FROM resume_outbox WHERE sync_id=?', (sync_id,)).fetchone()[0]

    def begin_write(self, row):
        with self.store.db(True) as db:
            return db.execute('UPDATE resume_outbox SET writes=writes+1 WHERE ticket=? AND writes=?',
                              (row['ticket'], row['writes'])).rowcount == 1

    def defer(self, row, due, failures=0, sent_id=None, sent_time=None):
        with self.store.db(True) as db:
            return db.execute('UPDATE resume_outbox SET due=?,failures=?,sent_id=?,sent_time=? WHERE ticket=?',
                              (due, failures, sent_id, sent_time, row['ticket'])).rowcount == 1

    def finish(self, row):
        with self.store.db(True) as db:
            return db.execute('DELETE FROM resume_outbox WHERE ticket=?', (row['ticket'],)).rowcount == 1
