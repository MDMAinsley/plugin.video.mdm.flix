"""Small bounded cache of chapter observations by hashed release/episode identity."""
import hashlib
import json
import os
import re
import sqlite3
import time
import xbmcvfs


def fingerprint(row):
    from resources.lib.playback.progress import clean,key,ProgressError
    try:
        extra=row.get('extra') or {};item=clean(extra.get('item'))
        release=extra.get('hash')
        if not isinstance(release,str) or not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[A-Z2-7a-z2-7]{32})',release):
            release=row.get('url')
            if not isinstance(release,str) or not release:return None
        return hashlib.sha256(json.dumps([release.lower() if extra.get('hash')==release else release,key(item)]).encode()).hexdigest()
    except (ProgressError,AttributeError,TypeError):return None


class Facts:
    def __init__(self,addon):self.path=os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'chapter_facts.sqlite')
    def db(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        db=sqlite3.connect(self.path,timeout=.2)
        try:
            db.execute('PRAGMA cache_size=-64')
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):db.close();return None
            db.execute('CREATE TABLE IF NOT EXISTS facts (identity TEXT PRIMARY KEY, chapters INTEGER, updated INTEGER)');db.execute('PRAGMA user_version=1')
            return db
        except sqlite3.Error:db.close();raise
    def remember(self,identity,chapters):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity) or type(chapters) is not bool:return
        db=None
        try:
            db=self.db()
            if db is None:return
            db.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?)',(identity,int(chapters),int(time.time())))
            db.execute('DELETE FROM facts WHERE identity IN (SELECT identity FROM facts ORDER BY updated DESC,identity LIMIT -1 OFFSET 1000)');db.commit()
        except (sqlite3.Error,OSError):pass
        finally:
            if db:db.close()
    def annotate(self,rows):
        db=None;known={}
        try:
            db=self.db()
            if db is not None:known=dict(db.execute('SELECT identity,chapters FROM facts WHERE updated>?',(int(time.time())-90*86400,)))
        except (sqlite3.Error,OSError):pass
        finally:
            if db:db.close()
        result=[]
        for row in rows:
            extra=dict(row.get('extra') or {});identity=fingerprint(row)
            if identity in known:extra['has_chapters']=bool(known[identity])
            result.append(dict(row,extra=extra))
        return result
