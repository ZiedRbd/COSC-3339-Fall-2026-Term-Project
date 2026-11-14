"""Values every template can use."""


def notifications(request):
    """The signed-in user's unread notifications, newest first, for the bell in the nav."""
    if not request.user.is_authenticated:
        return {}
    # A deleted ticket's notifications leave the bell with it
    unread = request.user.notifications.filter(read_at__isnull=True).exclude(incident__is_deleted=True)
    return {"unread_count": unread.count(), "unread_notifications": unread[:10]}
