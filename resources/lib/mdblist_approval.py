"""Kodi's phone approval layout with a local QR and a text fallback."""
from pathlib import Path
from threading import Event, Thread

import xbmcgui


def show(session, monitor, poll):
    if hasattr(xbmcgui, 'WindowXMLDialog'):
        try:
            return show_qr(session, monitor, poll)
        except (AttributeError, RuntimeError):
            pass
    progress = xbmcgui.DialogProgress()
    progress.create('Connect MDBList', 'On your phone, open {}\nEnter code {}'.format(
        session['verification_uri'], session['user_code']))
    try:
        return poll(lambda: progress.iscanceled() or monitor.waitForAbort(.2))
    finally:
        progress.close()


def show_qr(session, monitor, poll):
    class ApprovalDialog(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.getControl(10).setLabel(session['verification_uri'])
            self.getControl(11).setLabel(session['user_code'])
            self.setFocusId(20)
            if self.worker is None:
                self.worker = Thread(target=self.poll_approval, daemon=True)
                self.worker.start()

        def poll_approval(self):
            try:
                self.result = poll(lambda: self.cancelled.wait(.2) or monitor.abortRequested())
            except Exception as error:
                self.error = error
            finally:
                if not self.cancelled.is_set() and not monitor.abortRequested():
                    self.close()

        def onClick(self, control):
            if control == 20:
                self.cancel()

        def onAction(self, action):
            if action.getId() in (9, 10, 92):
                self.cancel()

        def cancel(self):
            self.cancelled.set()
            self.close()

    root = Path(__file__).resolve().parents[2]
    dialog = ApprovalDialog('MDBListApproval.xml', str(root), 'Default', '1080i')
    dialog.cancelled, dialog.result, dialog.error, dialog.worker = Event(), None, None, None
    try:
        dialog.doModal()
        if dialog.cancelled.is_set() or monitor.abortRequested():
            return None
        if dialog.error:
            raise dialog.error
        return dialog.result
    finally:
        dialog.cancelled.set()
