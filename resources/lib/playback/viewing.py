"""Select viewing records for Kodi UI and playback from the active backend."""
from .progress import Store, ProgressError, clean, key, seconds
from .resume_outbox import Outbox
from .viewing_outbox import Actions
from ..mdblist_account import State
from ..mdblist_client import MDBError


class Viewing:
    def __init__(self, addon):
        self.local = Store(addon)
        self.remote, self.pending = {}, set()
        self.edits = {}
        self.removals = {}
        self.account = None
        if addon.getSetting('progress_enabled') == 'false':
            return
        try:
            state = State(addon)
            self.account = state.connection()
            sync_id, records = state.playback_snapshot()
            if not sync_id or not self.account or self.account.get('sync_id') != sync_id:
                return
            self.pending = Outbox(self.local).identities(sync_id)
            self.edits = Actions(self.local).kinds(sync_id)
            self.removals = state.viewing_removals(sync_id)
            for item, position, duration, updated in records:
                item = clean(item)
                self.remote[key(item)] = dict(item=item, position=seconds(position), last_position=position,
                                              duration=seconds(duration), watched=False, updated=updated)
            for item, updated in state.watched_snapshot(sync_id):
                item = clean(item)
                identity = key(item)
                resume = self.remote.get(identity)
                if not resume or updated >= resume['updated']:
                    self.remote[identity] = dict(item=item,position=0,last_position=0,duration=0,watched=True,updated=updated)
        except (MDBError, ProgressError, TypeError, ValueError):
            self.remote.clear()

    @staticmethod
    def choose(local, remote):
        if not local or not remote:
            return local or remote
        if remote['updated'] <= local['updated']:
            return local
        duration = local['duration']
        if duration and remote['duration'] and abs(remote['duration']-duration) > max(60,duration*.05):
            return local
        if not (local['watched'] or remote['watched']) and abs(remote['position']-local['position']) <= 1:
            return local
        return dict(remote,item=dict(remote['item'],**local['item']))

    def resolve(self, identity, local):
        if self.edits.get(identity) == 'clear':
            return None
        if identity in self.pending or identity in self.edits:
            return local
        if local:
            kind = 'watched' if local['watched'] else 'playback'
            removed = self.removals.get(kind,{}).get(identity)
            if removed and local['updated'] <= removed[0]:
                if local['watched'] and local['updated'] <= removed[1][0]+1:
                    local = None
                elif not local['watched']:
                    position,duration,_ = removed[1]
                    if abs(position-local['position']) <= 1 and abs(duration-local['duration']) <= max(60,duration*.05):
                        local = None
        return self.choose(local,self.remote.get(identity))

    def get(self, item):
        identity = key(item)
        local = self.local.get(item)
        return self.resolve(identity,local)

    def merged(self):
        local = {key(row['item']):row for row in self.local.rows(False)}
        return [record for identity in local.keys() | self.remote.keys()
                if (record:=self.resolve(identity,local.get(identity)))]

    def rows(self, continuing=True):
        if not (self.remote or self.edits or self.removals):
            return self.local.rows(continuing)
        records = self.merged()
        if continuing:
            records = [row for row in records if not row['watched'] and row['position'] >= 30]
        return sorted(records,key=lambda row:(-row['updated'],key(row['item'])))[:40 if continuing else 1000]

    def watched_keys(self):
        return {key(row['item']) for row in self.merged() if row['watched']}
