"""Finding a campus building from what somebody typed."""
import re
import unicodedata


def normalize(text):
    """
    Lower case, no accents, no punctuation, single spaces, so that two
    spellings of one name compare equal.
    "Jacques Dujarié Hall" becomes "jacques dujarie hall".
    """
    # Split every accented letter into the plain letter and its accent mark, then drop the marks
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Anything that is not a letter or a digit becomes one space
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def names_of(building):
    """The building's name and each of its short names, normalized."""
    names = [building.name] + (building.aliases or "").split(",")
    return [name for name in (normalize(n) for n in names) if name]


def matches(query, building):
    """
    True when every typed word is the beginning of a word in the
    building's name, or in one of its short names. "nat sci" fits Natural
    Sciences Center, and "lbj" fits Lady Bird Johnson Hall through its
    short name.
    """
    typed = normalize(query).split()
    return any(
        all(any(word.startswith(part) for word in name.split()) for part in typed)
        for name in names_of(building)
    )


def closeness(query, building):
    """
    How well a building fits what was typed: 0 when the text is exactly
    its name or one of its short names, 1 when a name begins with the
    text, 2 when the text is only found further inside a name.
    """
    typed = normalize(query)
    names = names_of(building)
    if typed in names:
        return 0
    if any(name.startswith(typed) for name in names):
        return 1
    return 2


def search(query, buildings):
    """
    The buildings that match what was typed, closest first: an exact
    name, then names that begin with the text, then the rest.
    Alphabetical inside each group.
    """
    found = [b for b in buildings if matches(query, b)]
    return sorted(found, key=lambda b: (closeness(query, b), normalize(b.name)))


def best_match(text, buildings):
    """
    The one building a piece of free text most likely means, or None.
    Used for tickets written before the building list existed. It only
    answers when it is sure: one match, or a first match that is closer
    than the second. Text that says more than a name, such as
    "Moody 214", is given to the one building named inside it.
    """
    typed = normalize(text)
    found = search(text, buildings) if typed else []
    if len(found) == 1:
        return found[0]
    if len(found) > 1 and closeness(text, found[0]) < closeness(text, found[1]):
        return found[0]
    if found or not typed:
        return None
    inside = [b for b in buildings if any(f" {name} " in f" {typed} " for name in names_of(b))]
    return inside[0] if len(inside) == 1 else None
