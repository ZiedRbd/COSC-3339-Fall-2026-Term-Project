"""Values every template can use."""
from .json_settings import SETTINGS, picture_format_names


def notifications(request):
    """The signed-in user's unread notifications, newest first, for the bell in the nav."""
    if not request.user.is_authenticated:
        return {}
    # A deleted ticket's notifications leave the bell with it
    unread = request.user.notifications.filter(read_at__isnull=True).exclude(incident__is_deleted=True)
    return {"unread_count": unread.count(), "unread_notifications": unread[:SETTINGS["notifications"]["unread_shown_in_the_bell"]]}


def site_settings(request):
    """The settings from config/settings.json, so a page shows the same limits the server enforces."""
    return {"site_settings": SETTINGS, "profile_picture_formats_in_words": picture_format_names()}
