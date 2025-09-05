# region ISERO PATCH sales-utils
import os
import math


def calc_total(unit: float, qty: int, bulk_min: int, off_each: float) -> tuple[float, float, float]:
    """Visszaadja: (subtotal, discount, total)"""
    qty = max(1, int(qty))
    subtotal = unit * qty
    discount = (off_each * qty) if qty >= bulk_min else 0.0
    return subtotal, discount, subtotal - discount


def env_prices():
    unit = float(os.getenv("MEBINU_BASE_PRICE_USD", "30") or "30")
    bulk_min = int(os.getenv("MEBINU_BULK_MIN_QTY", "4") or "4")
    off_each = float(os.getenv("MEBINU_BULK_OFF_USD", "5") or "5")
    return unit, bulk_min, off_each
# endregion ISERO PATCH sales-utils

# region ISERO PATCH commission-sales
def calc_images(unit: float, qty: int, bulk_min: int, off_each: float):
    """Képár kalkuláció (db x egységár, kedvezménnyel)."""
    qty = max(1, int(qty))
    subtotal = unit * qty
    discount = (off_each * qty) if qty >= bulk_min else 0.0
    return subtotal, discount, subtotal - discount


def calc_videos(price_per_5s: float, seconds_per_video: int, qty: int, bulk_min: int, off_each: float):
    """Videó kalkuláció. Minden videó hossza 5 mp-es blokkokra kerekít."""
    qty = max(1, int(qty))
    blocks = max(1, math.ceil(max(1, int(seconds_per_video)) / 5))
    per_video = price_per_5s * blocks
    subtotal = per_video * qty
    discount = (off_each * qty) if qty >= bulk_min else 0.0
    return per_video, subtotal, discount, subtotal - discount
# endregion ISERO PATCH commission-sales
