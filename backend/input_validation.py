"""Small validation helpers for values persisted by API routes."""
import math


def coordinates(latitude, longitude, *, form=False):
    """Return bounded finite coordinates; multipart form numbers arrive as strings."""
    def number(value):
        if type(value) in (int, float) or (form and isinstance(value, str) and value.strip()):
            try:
                result = float(value)
            except (ValueError, OverflowError):
                pass
            else:
                if math.isfinite(result):
                    return result
        raise ValueError('latitude and longitude must be finite numbers')

    lat, lng = number(latitude), number(longitude)
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('latitude or longitude is out of range')
    return lat, lng


def positive_integer(value, *, form=False):
    if form and isinstance(value, str) and value.isascii() and value.isdigit():
        try:
            value = int(value)
        except ValueError:
            raise ValueError('must be a positive integer') from None
    if type(value) is not int or not 0 < value <= 2_147_483_647:
        raise ValueError('must be a positive integer')
    return value
