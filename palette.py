"""World Cup color theme on top of tui's neutral base (FIFA-ish)."""

from tui.theme import Theme


class WorldCupTheme(Theme):
    gold = (240, 196, 88)     # scorers / highlight
    red = (235, 92, 92)       # red cards / losses
    yellow = (236, 200, 92)   # yellow cards
    live = (90, 220, 140)
    pitch = (32, 110, 64)


P = WorldCupTheme
