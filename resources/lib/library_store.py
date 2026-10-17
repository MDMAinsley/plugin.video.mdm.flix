"""Bounded local personal library. TMDB identities, never source/credential storage."""
import os
import re
import sqlite3
from contextlib import contextmanager
import xbmcvfs

MAX_TITLES = 500
MAX_LISTS = 20
MAX_MEMBERS = 2000


class LibraryError(Exception):
    pass


def identity(media, identifier):
    if media not in ('movie', 'tv') or type(identifier) is bool or not re.fullmatch(r'[0-9]{1,10}',str(identifier)) or not 0 < int(identifier) < 2147483647:
        raise LibraryError('Invalid film or TV identity.')
    return media, int(identifier)


def list_id(value):
    if type(value) is bool or not re.fullmatch(r'[0-9]{1,10}',str(value)) or not 0 < int(value) < 2147483647:
        raise LibraryError('Invalid list.')
    return int(value)


def clean_name(value):
    if not isinstance(value, str):
        raise LibraryError('Enter a list name.')
    value = ' '.join(value.split())
    if not value or len(value) > 50 or any(ord(c) < 32 for c in value):
        raise LibraryError('Use a list name of 1–50 characters.')
    return value


def metadata(raw, media, identifier):
    identity(media, identifier)
    if not isinstance(raw, dict) or raw.get('adult') is True or str(raw.get('id')) != str(identifier):
        raise LibraryError('The title information does not match this film or show.')
    title = raw.get('title') if media == 'movie' else raw.get('name')
    if not isinstance(title, str) or not title.strip():
        raise LibraryError('This title has no usable name.')
    image = lambda key: raw.get(key) if isinstance(raw.get(key), str) and re.fullmatch(r'/[A-Za-z0-9._-]{1,200}', raw[key]) else ''
    date = raw.get('release_date' if media == 'movie' else 'first_air_date')
    date = date if isinstance(date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else ''
    plot = raw.get('overview')
    return dict(media=media, tmdb_id=int(identifier), title=title.strip()[:200], date=date,
                plot=plot[:2000] if isinstance(plot, str) else '', poster=image('poster_path'), backdrop=image('backdrop_path'))


class Library:
    def __init__(self, addon):
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        if not profile:
            raise LibraryError('Kodi could not locate the Flix profile.')
        self.path = os.path.join(profile, 'personal_library.sqlite')

    @contextmanager
    def db(self, write=False):
        connection = None
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=1)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA cache_size=-256')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise LibraryError('This library belongs to a newer Flix version. Update Flix to use it.')
            if version == 0:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('CREATE TABLE IF NOT EXISTS titles(media TEXT, tmdb_id INTEGER, title TEXT, date TEXT, plot TEXT, poster TEXT, backdrop TEXT, personal_rating INTEGER NOT NULL DEFAULT 0 CHECK(personal_rating BETWEEN 0 AND 10), PRIMARY KEY(media,tmdb_id))')
                connection.execute('CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE)')
                connection.execute('CREATE TABLE IF NOT EXISTS members(list_id INTEGER REFERENCES lists(id) ON DELETE CASCADE, media TEXT, tmdb_id INTEGER, position INTEGER, PRIMARY KEY(list_id,media,tmdb_id), FOREIGN KEY(media,tmdb_id) REFERENCES titles(media,tmdb_id) ON DELETE CASCADE)')
                connection.execute("INSERT OR IGNORE INTO lists(id,name,normalized) VALUES(1,'My List','my list')")
                connection.execute('PRAGMA user_version=1')
                connection.commit()
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.commit()
        except (sqlite3.Error, OSError):
            raise LibraryError('Your library could not be read or saved. Check free storage, close another library action and retry. Existing data has been kept.') from None
        finally:
            if connection:
                connection.close()  # Rolls back any incomplete transaction.

    @staticmethod
    def _list(db, identifier):
        identifier = list_id(identifier)
        if not db.execute('SELECT id FROM lists WHERE id=?', (identifier,)).fetchone():
            raise LibraryError('That list no longer exists. Open My Library again.')
        return identifier

    @staticmethod
    def _put(db, row):
        media, identifier = identity(row['media'], row['tmdb_id'])
        exists = db.execute('SELECT 1 FROM titles WHERE media=? AND tmdb_id=?', (media, identifier)).fetchone()
        if not exists and db.execute('SELECT count(*) FROM titles').fetchone()[0] >= MAX_TITLES:
            raise LibraryError('This device library is limited to 500 titles. Remove unneeded saved/rated titles first.')
        db.execute('INSERT INTO titles(media,tmdb_id,title,date,plot,poster,backdrop) VALUES(?,?,?,?,?,?,?) ON CONFLICT(media,tmdb_id) DO UPDATE SET title=excluded.title,date=excluded.date,plot=excluded.plot,poster=excluded.poster,backdrop=excluded.backdrop', tuple(row[key] for key in ('media','tmdb_id','title','date','plot','poster','backdrop')))

    def lists(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT l.id,l.name,count(m.tmdb_id) AS count FROM lists l LEFT JOIN members m ON m.list_id=l.id GROUP BY l.id ORDER BY l.id LIMIT 20')]

    def create(self, name):
        name = clean_name(name)
        with self.db(True) as db:
            if db.execute('SELECT id FROM lists WHERE normalized=?', (name.casefold(),)).fetchone():
                raise LibraryError('A list with that name already exists.')
            if db.execute('SELECT count(*) FROM lists').fetchone()[0] >= MAX_LISTS:
                raise LibraryError('You can keep up to 20 lists on this device.')
            return db.execute('INSERT INTO lists(name,normalized) VALUES(?,?)', (name,name.casefold())).lastrowid

    def rename(self, identifier, name):
        name = clean_name(name)
        with self.db(True) as db:
            identifier = self._list(db, identifier)
            if identifier == 1:
                raise LibraryError('My List keeps its standard name.')
            if db.execute('SELECT id FROM lists WHERE normalized=? AND id<>?', (name.casefold(), identifier)).fetchone():
                raise LibraryError('A list with that name already exists.')
            db.execute('UPDATE lists SET name=?,normalized=? WHERE id=?', (name,name.casefold(),identifier))

    @staticmethod
    def _prune(db):
        db.execute('DELETE FROM titles WHERE personal_rating=0 AND NOT EXISTS(SELECT 1 FROM members m WHERE m.media=titles.media AND m.tmdb_id=titles.tmdb_id)')

    def delete(self, identifier):
        with self.db(True) as db:
            identifier = self._list(db, identifier)
            if identifier == 1:
                raise LibraryError('My List cannot be deleted. Remove individual titles instead.')
            db.execute('DELETE FROM lists WHERE id=?', (identifier,)); self._prune(db)

    def get(self, media, identifier):
        media,identifier = identity(media, identifier)
        with self.db() as db:
            row = db.execute('SELECT * FROM titles WHERE media=? AND tmdb_id=?', (media,identifier)).fetchone()
            return dict(row) if row else None

    def memberships(self, media, identifier):
        media,identifier=identity(media,identifier)
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT l.id,l.name FROM lists l JOIN members m ON l.id=m.list_id WHERE m.media=? AND m.tmdb_id=? ORDER BY l.id LIMIT 20',(media,identifier))]

    def add(self, row, identifier=1):
        with self.db(True) as db:
            identifier = self._list(db, identifier); self._put(db, row)
            params = (identifier,row['media'],row['tmdb_id'])
            if db.execute('SELECT 1 FROM members WHERE list_id=? AND media=? AND tmdb_id=?', params).fetchone():
                return
            if db.execute('SELECT count(*) FROM members').fetchone()[0] >= MAX_MEMBERS:
                raise LibraryError('This device has reached its 2000 saved-list entries limit.')
            position = db.execute('SELECT coalesce(max(position),0)+1 FROM members WHERE list_id=?', (identifier,)).fetchone()[0]
            db.execute('INSERT INTO members VALUES(?,?,?,?)', params+(position,))

    def remove(self, identifier, media, tmdb_id):
        media,tmdb_id = identity(media,tmdb_id)
        with self.db(True) as db:
            identifier = self._list(db,identifier)
            db.execute('DELETE FROM members WHERE list_id=? AND media=? AND tmdb_id=?', (identifier,media,tmdb_id)); self._prune(db)

    def rate(self, row, value):
        if type(value) is not int or not 0 <= value <= 10:
            raise LibraryError('Choose your rating from 1–10, or clear it.')
        with self.db(True) as db:
            self._put(db,row)
            db.execute('UPDATE titles SET personal_rating=? WHERE media=? AND tmdb_id=?', (value,row['media'],row['tmdb_id'])); self._prune(db)

    def rows(self, identifier=None, kind='all'):
        if kind not in ('all','movie','tv','rated'):
            raise LibraryError('Invalid library filter.')
        with self.db() as db:
            params=[]
            if identifier is not None:
                identifier=self._list(db,identifier)
                sql='SELECT t.* FROM titles t JOIN members m ON m.media=t.media AND m.tmdb_id=t.tmdb_id WHERE m.list_id=?';params.append(identifier)
            else:
                sql='SELECT t.* FROM titles t WHERE (t.personal_rating>0 OR EXISTS(SELECT 1 FROM members m WHERE m.media=t.media AND m.tmdb_id=t.tmdb_id))'
            if kind in ('movie','tv'):
                sql+=' AND t.media=?';params.append(kind)
            if kind=='rated':
                sql+=' AND t.personal_rating>0'
            sql+=' ORDER BY '+('m.position,t.media,t.tmdb_id' if identifier is not None else 't.title COLLATE NOCASE,t.media,t.tmdb_id')+' LIMIT 500'
            return [dict(row) for row in db.execute(sql,params)]

    def move(self, identifier, media, tmdb_id, direction):
        if direction not in (-1,1):
            raise LibraryError('Invalid list movement.')
        media,tmdb_id=identity(media,tmdb_id)
        with self.db(True) as db:
            identifier=self._list(db,identifier)
            rows=db.execute('SELECT media,tmdb_id FROM members WHERE list_id=? ORDER BY position,media,tmdb_id',(identifier,)).fetchall()
            keys=[(r['media'],r['tmdb_id']) for r in rows]
            if (media,tmdb_id) not in keys:
                raise LibraryError('This title is no longer in this list.')
            index=keys.index((media,tmdb_id));target=index+direction
            if 0 <= target < len(keys):
                keys[index],keys[target]=keys[target],keys[index]
                for position,(kind,number) in enumerate(keys,1):
                    db.execute('UPDATE members SET position=? WHERE list_id=? AND media=? AND tmdb_id=?',(position,identifier,kind,number))
