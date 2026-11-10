"""Present the existing title actions in a remote-friendly Home dialog."""
from pathlib import Path

import xbmc
import xbmcgui

from resources.lib.playback import progress_ui


class TitleActions:
    def __init__(self):
        self.title = 'Title actions'
        self.plot = ''
        self.image = ''
        self.entries = []
        self.selected = 0

    def category(self, title):
        self.title = title

    def add(self, command, label, action, params=None, artwork=None, info=None):
        if not self.entries:
            art = artwork or {}
            self.image = art.get('fanart') or art.get('thumb') or art.get('poster') or ''
            self.plot = (info or {}).get('plot') or ''
        self.entries.append((label, command, dict(params or {}, action=action)))

    def add_folder(self, label, action, **metadata):
        self.add('ActivateWindow(Videos,{},return)', label, action, **metadata)

    def add_playable(self, label, action, **metadata):
        self.add('PlayMedia({})', label, action, **metadata)

    def add_action(self, label, action, **metadata):
        self.add('RunPlugin({})', label, action, **metadata)

    def end(self, _content=None):
        pass  # The modal uses the entries without opening a Kodi directory.


def choose(actions):
    class TitleDialog(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.getControl(10).setText(actions.title)
            self.getControl(11).setText(actions.plot)
            self.getControl(12).setImage(actions.image)
            entries = self.getControl(101)
            entries.reset()
            entries.addItems([xbmcgui.ListItem(label=label) for label, _, _ in actions.entries])
            entries.selectItem(actions.selected)
            self.setFocusId(101)

        def onClick(self, control):
            if control == 101:
                self.choice = self.getControl(101).getSelectedPosition()
                self.close()
            elif control == 102:
                self.close()

        def onAction(self, action):
            if action.getId() in (9, 10, 92):
                self.close()

    root = Path(__file__).resolve().parents[2]
    dialog = TitleDialog('MDMHomeTitle.xml', str(root), 'Default', '1080i')
    dialog.choice = -1
    dialog.doModal()
    return dialog.choice


def show(nav, addon, core, params):
    actions = TitleActions()
    progress_ui.show(actions, addon, core, dict(params, action='progress_details'))
    if not actions.entries:
        return
    while True:
        try:
            selected = choose(actions)
        except (AttributeError, RuntimeError):
            selected = xbmcgui.Dialog().select(actions.title, [label for label, _, _ in actions.entries], preselect=actions.selected)
        if not 0 <= selected < len(actions.entries):
            return
        _, command, target = actions.entries[selected]
        if target['action'] == 'trailer_play':
            from resources.lib.catalogue.trailers import play
            if play(addon, core, target):
                return
            actions.selected = selected
            continue
        xbmc.executebuiltin(command.format(nav.build_url(**target)))
        return
