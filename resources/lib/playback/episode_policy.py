"""Episode timing decisions and bounded per-show preferences, never stream URLs."""
import math
import os
import re
import sqlite3
from contextlib import contextmanager
import xbmcvfs


class EpisodeError(Exception):pass


def finite(value,minimum=0,maximum=86400):
    if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise EpisodeError('Invalid episode timing.')
    return float(value)


def timing(text):
    if not isinstance(text,str) or not re.fullmatch(r'\d{1,5}(?::[0-5]\d){0,2}',text.strip()):
        raise EpisodeError('Enter seconds, M:SS or H:MM:SS, for example 90 or 1:30.')
    result=0
    for part in text.strip().split(':'):result=result*60+int(part)
    return int(finite(result,0,14400))


def bounded_setting(addon,name,default,minimum,maximum):
    try:return finite(float(addon.getSetting(name)),minimum,maximum)
    except (EpisodeError,ValueError,TypeError):return default


def enabled(addon,name,default=True):
    value=addon.getSetting(name)
    return default if value not in ('true','false') else value=='true'


def configuration(addon,preset=None):
    preset=preset or {}
    return dict(enabled=preset.get('enabled',enabled(addon,'episode_new_shows')),
                next_enabled=enabled(addon,'episode_next_enabled'),
                next_mode=addon.getSetting('episode_next_mode') or 'Chapters',
                percent=bounded_setting(addon,'episode_next_percent',95,50,99),
                remaining=bounded_setting(addon,'episode_next_seconds',60,5,600),
                intro_enabled=enabled(addon,'episode_intro_enabled'),
                intro_mode=preset.get('intro_mode','Chapters'),
                start=preset.get('start',0),end=preset.get('end',0))


def chapter_marks(raw,duration):
    """Require finite increasing seconds. Numbered chapters alone say nothing."""
    if not isinstance(raw,list) or len(raw)>500 or duration<=0:return []
    result=[];previous=-1
    for row in raw:
        if not isinstance(row,dict):return []
        try:at=finite(row.get('time'),0,duration)
        except EpisodeError:return []
        if at<=previous:return []
        previous=at
        result.append((at,str(row.get('name') or '')[:200].casefold().strip()))
    return result


def named(name,words):
    # Avoid treating 'Introduction to Physics' or 'No credits' as markers.
    return name in words


INTRO={'intro','opening','opening credits','opening titles','title sequence','op'}
CREDITS={'credits','end credits','closing credits','ending credits','outro','ending','ed'}


def intro_range(config,chapters,duration):
    if not config['enabled'] or not config['intro_enabled'] or duration<60:return None
    if config['intro_mode']=='Off':return None
    if config['intro_mode']=='Chapters':
        for index,(start,name) in enumerate(chapters[:-1]):
            end=chapters[index+1][0]
            if named(name,INTRO) and 0<=start<min(900,duration*.5) and 3<=end-start<=600 and end<duration-30:
                return start,end
    # A saved range is the explicit fallback when the file lacks labelled chapters.
    start,end=config['start'],config['end']
    if 0<=start<end and end-start<=600 and end<duration-30:return start,end
    return None


def next_at(config,chapters,duration):
    if not config['enabled'] or not config['next_enabled'] or duration<60:return None
    mode=config['next_mode']
    if mode=='Chapters':
        for start,name in chapters:
            if named(name,CREDITS) and duration*.5<=start<=duration-3:return start
        mode='Seconds from end'
    if mode=='Watch percentage':return duration*config['percent']/100
    # Never offer Next episode in the opening half of a short file.
    return max(duration*.5,duration-config['remaining'])


class Presets:
    def __init__(self,addon):
        self.path=os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'episode_presets.sqlite')

    @contextmanager
    def db(self):
        db=None
        try:
            os.makedirs(os.path.dirname(self.path),exist_ok=True)
            db=sqlite3.connect(self.path,timeout=1);db.row_factory=sqlite3.Row
            db.execute('PRAGMA cache_size=-128')
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise EpisodeError('Update Flix to read these newer episode presets.')
            db.execute('CREATE TABLE IF NOT EXISTS shows (id INTEGER PRIMARY KEY,title TEXT,enabled INTEGER,mode TEXT,start REAL,end REAL)')
            db.execute('PRAGMA user_version=1')
            yield db
            db.commit()
        except (sqlite3.Error,OSError):raise EpisodeError('Episode preferences could not be saved. Check device storage; existing presets are kept.') from None
        finally:
            if db:db.close()

    @staticmethod
    def identifier(value):
        if not re.fullmatch('[0-9]{1,10}',str(value)) or not 0<int(value)<2147483647:raise EpisodeError('Invalid show identity.')
        return int(value)

    def get(self,identifier):
        with self.db() as db:
            row=db.execute('SELECT * FROM shows WHERE id=?',(self.identifier(identifier),)).fetchone()
            return dict(enabled=bool(row['enabled']),intro_mode=row['mode'],start=row['start'],end=row['end'],title=row['title']) if row else None

    def save(self,identifier,title,active,mode,start=0,end=0):
        identifier=self.identifier(identifier)
        if type(active) is not bool or mode not in ('Chapters','Custom','Off'):raise EpisodeError('Invalid episode preset.')
        start=finite(start,0,14400);end=finite(end,0,14400)
        if (start or end) and not 0<end-start<=600:raise EpisodeError('Intro end must follow its start by at most 10 minutes.')
        if mode=='Custom' and end<=start:raise EpisodeError('Save an intro start and end first.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM shows WHERE id=?',(identifier,)).fetchone() and db.execute('SELECT count(*) FROM shows').fetchone()[0]>=500:
                raise EpisodeError('There are 500 show presets. Remove an unused one before adding another.')
            db.execute('INSERT OR REPLACE INTO shows VALUES(?,?,?,?,?,?)',(identifier,str(title)[:200],int(active),mode,start,end))

    def rows(self):
        with self.db() as db:return [dict(row) for row in db.execute('SELECT * FROM shows ORDER BY title,id LIMIT 500')]

    def remove(self,identifier):
        with self.db() as db:db.execute('DELETE FROM shows WHERE id=?',(self.identifier(identifier),))
