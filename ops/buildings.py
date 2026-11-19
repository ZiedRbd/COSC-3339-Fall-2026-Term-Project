"""Finding a campus building from what somebody typed."""
import re
import unicodedata

# Words that only say where inside a building something is. Typed text may
# carry these around a building's name and still be about that building.
DETAIL_WORDS = {
    "room", "rm", "floor", "fl", "level", "lobby", "basement", "lab", "office", "hall", "hallway", "entrance",
    "stairs", "stairwell", "restroom", "bathroom", "kitchen", "lounge", "wing", "side", "front", "back", "door",
    "building", "bldg", "cafe", "apartment", "apartments", "apt", "apts", "upstairs", "downstairs",
    "east", "west", "north", "south", "the", "in", "at", "of", "near", "by", "outside", "inside", "behind",
    "next", "to", "on",
}


def normalize(text):
    """
    Lower case, no accents, no punctuation, single spaces, so that two
    spellings of one name compare equal.
    "Jacques Dujarié Hall" becomes "jacques dujarie hall".
    """
    # Split every accented letter into the plain letter and its accent mark, then drop the marks
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Anything that is not a letter or a digit, in any alphabet, becomes one space
    return re.sub(r"[\W_]+", " ", text).strip()


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
    For a search box, where a person picks from what is offered: the
    buildings that match what was typed, closest first. An exact name,
    then names that begin with the text, then the rest, alphabetical
    inside each group. Nothing typed offers every building.
    """
    found = [b for b in buildings if matches(query, b)]
    return sorted(found, key=lambda b: (closeness(query, b), normalize(b.name)))


def _is_detail(word):
    """A word that says where inside a building: "lobby", "3rd", "214", or a wing's letter."""
    return word in DETAIL_WORDS or len(word) == 1 or any(ch.isdigit() for ch in word)


def _without(words, name_words):
    """The words left once every run of name_words is taken out of words."""
    left, position, length = [], 0, len(name_words)
    while position < len(words):
        if words[position:position + length] == name_words:
            position += length
        else:
            left.append(words[position])
            position += 1
    return left


def name_found_in(typed_words, building):
    """
    The longest of the building's names that the typed words spell out in
    full, when everything else typed only says where inside it. None when
    the text is not clearly about this building. "Moody 214" names Moody
    Hall through its short name; "Main St entrance" names nothing, because
    "st" is not a place inside a building.
    """
    longest = None
    for name in names_of(building):
        left = _without(typed_words, name.split())
        if len(left) < len(typed_words) and all(_is_detail(word) for word in left):
            if longest is None or len(name) > len(longest):
                longest = name
    return longest


def best_match(text, buildings):
    """
    The one building a piece of free text is clearly about, or None. With
    nobody there to confirm, it has to be sure: a wrong building on a
    ticket is worse than none. So the text must spell out a whole name or
    short name of the building, and nothing else but words for a place
    inside it. The beginning of a word, which is enough for a search box,
    is not enough here.

    When the text names two buildings it is about neither, unless one name
    sits inside the other, as "Moreau" does inside "Moreau Casitas": then
    it is about the longer one.
    """
    typed_words = normalize(text).split()
    if not typed_words:
        return None
    named = [(building, name) for building in buildings
             for name in [name_found_in(typed_words, building)] if name is not None]
    if not named:
        return None
    best, best_name = max(named, key=lambda pair: len(pair[1]))
    for building, name in named:
        if building is best:
            continue
        if name == best_name or f" {name} " not in f" {best_name} ":
            return None
    return best
