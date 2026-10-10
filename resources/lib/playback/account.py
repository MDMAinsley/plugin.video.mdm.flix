import time
import xbmc
import xbmcgui
from resources.lib.playback.alldebrid import AllDebrid
from resources.lib.playback.errors import PlaybackError, Cancelled


def authorise(addon):
    client=AllDebrid(addon)
    progress=None
    try:
        info=client.request('v4.1/pin/get',authenticated=False)
        pin,check=info.get('pin'),info.get('check')
        if not isinstance(pin,str) or not pin.isalnum() or not isinstance(check,str) or not check:
            raise PlaybackError('AllDebrid returned invalid PIN details. Try authorising again.')
        expires=info.get('expires_in',600)
        expires=min(expires,600) if type(expires) is int and expires>0 else 600
        deadline=time.monotonic()+expires
        progress=xbmcgui.DialogProgress()
        progress.create('Authorise AllDebrid','Visit https://alldebrid.com/pin/\nEnter PIN: '+pin+'\nWaiting for authorisation…')
        monitor=xbmc.Monitor()
        while time.monotonic()<deadline:
            client.wait(progress,monitor)
            data=client.request('v4/pin/check',{'pin':pin,'check':check},authenticated=False)
            if data.get('activated') is True and isinstance(data.get('apikey'),str) and data['apikey']:
                addon.setSetting('alldebrid_api_key',data['apikey'])
                addon.setSetting('alldebrid_enabled','true')
                xbmcgui.Dialog().notification('MDM Flix','AllDebrid authorised.',xbmcgui.NOTIFICATION_INFO,3000)
                return
        raise PlaybackError('AllDebrid PIN expired. Start authorisation again.')
    except Cancelled:
        pass
    except PlaybackError as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure))
    finally:
        if progress: progress.close()


def check_account(addon):
    try:
        client=AllDebrid(addon)
        user=client.user()
        text='Authorisation: valid\nAllDebrid enabled: {}\nSubscription: {}'.format('yes' if client.enabled else 'no','active' if user.get('isPremium') is True else 'inactive / limited')
        xbmcgui.Dialog().textviewer('AllDebrid account',text)
    except PlaybackError as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure))


def disconnect(addon):
    if xbmcgui.Dialog().yesno('MDM Flix','Remove AllDebrid authorisation from this Kodi installation?'):
        addon.setSetting('alldebrid_api_key','')
        addon.setSetting('alldebrid_enabled','false')
        from resources.lib.session import clear_sources
        clear_sources()
        xbmcgui.Dialog().notification('MDM Flix','AllDebrid disconnected locally.',xbmcgui.NOTIFICATION_INFO,3000)
