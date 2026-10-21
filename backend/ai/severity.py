"""
ResQNet — Damage Severity Classification
"""


def classify_severity(image_path: str | None = None, disaster_type: str | None = None) -> str:
    """
    Unvalidated estimate using image-color thresholds or disaster-type rules.
    This does not independently identify disaster type, confirm structural damage,
    predict future conditions, or provide a calibrated confidence measurement.

    Returns one of:
        'Severe Damage', 'Moderate Damage', 'Low Damage'
    These are legacy estimate labels, not verified conditions or response advice.
    """
    if image_path:
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(image_path).convert('RGB').resize((64, 64))
            arr = np.array(img, dtype=float)

            brightness  = arr.mean() / 255.0
            red_ratio   = arr[:, :, 0].mean() / 255.0
            green_ratio = arr[:, :, 1].mean() / 255.0

            # Legacy brightness threshold; not evidence of smoke or damage.
            if brightness < 0.30:
                return 'Severe Damage'
            # Legacy red-channel threshold; not evidence of fire or damage.
            if red_ratio > 0.55:
                return 'Severe Damage'
            # Moderate indicators
            if brightness < 0.50 or (red_ratio > 0.45 and green_ratio < 0.40):
                return 'Moderate Damage'
            return 'Low Damage'

        except Exception:
            pass  # Fall through to rule-based

    # ── Rule-based fallback ────────────────────────────────────────────────
    SEVERE   = {'Earthquake', 'Cyclone'}
    MODERATE = {'Flood', 'Landslide', 'Fire'}

    if disaster_type in SEVERE:
        return 'Severe Damage'
    if disaster_type in MODERATE:
        return 'Moderate Damage'
    return 'Low Damage'
