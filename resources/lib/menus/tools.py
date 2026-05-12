import xbmcaddon


def show(nav, addon):
    nav.add_folder("Open MDM Flix Settings", "open_settings")
    nav.add_folder("Provider Settings", "provider_settings")
    nav.add_folder("Diagnostics", "diagnostics")
    nav.end()