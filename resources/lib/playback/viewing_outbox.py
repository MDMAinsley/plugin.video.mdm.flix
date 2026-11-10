"""Account-scoped watched and clear changes, independent of resume checkpoints."""
import json
import time
import uuid


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='viewing_outbox'").fetchone()


def enqueue(db, identity, item, action):
    scope, kind, recorded, boot = action
    db.execute('CREATE TABLE IF NOT EXISTS viewing_outbox (identity TEXT PRIMARY KEY, '
               'ticket TEXT NOT NULL, sync_id TEXT NOT NULL, kind TEXT NOT NULL, item TEXT NOT NULL, '
               'recorded REAL NOT NULL, boot TEXT, due REAL NOT NULL, writes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0)')
    db.execute('INSERT OR REPLACE INTO viewing_outbox(identity,ticket,sync_id,kind,item,recorded,boot,due) '
               'VALUES(?,?,?,?,?,?,?,?)',
               (identity,uuid.uuid4().hex,scope,kind,json.dumps(item,ensure_ascii=False),recorded,boot,time.time()))


class Actions:
    def __init__(self, store):
        self.store = store

    def pending(self, scope, boot):
        with self.store.db() as db:
            if exists(db):
                row = db.execute('SELECT * FROM viewing_outbox WHERE sync_id=? AND due<=? AND (boot IS NULL OR boot<>?) '
                                 'ORDER BY due,recorded LIMIT 1',(scope,time.time(),boot)).fetchone()
                if row:
                    return dict(row)

    def kinds(self, scope):
        with self.store.db() as db:
            if not exists(db):
                return {}
            return dict(db.execute('SELECT identity,kind FROM viewing_outbox WHERE sync_id=?',(scope,)))

    def begin(self, row):
        with self.store.db(True) as db:
            return db.execute('UPDATE viewing_outbox SET writes=writes+1 WHERE ticket=? AND writes=?',
                              (row['ticket'],row['writes'])).rowcount == 1

    def defer(self, row, delay, failures=0):
        with self.store.db(True) as db:
            return db.execute('UPDATE viewing_outbox SET due=?,failures=? WHERE ticket=?',
                              (time.time()+delay,failures,row['ticket'])).rowcount == 1

    def finish(self, row):
        with self.store.db(True) as db:
            return db.execute('DELETE FROM viewing_outbox WHERE ticket=?',(row['ticket'],)).rowcount == 1
