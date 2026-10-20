"""
ResQNet — Damage Severity Classification
"""


def classify_severity(image_path: str | None = None, disaster_type: str | None = None) -> str:
    """
    Classifies structural damage severity from an uploaded image.

    If an image_path is provided it uses PIL pixel-heuristics (placeholder
    for a real CV / scikit-learn model).  Falls back to disaster-type rules.

    Returns one of:
        'Severe Damage'   — Immediate response required
        'Moderate Damage' — Urgent but not life-threatening
        'Low Damage'      — Minor structural impact
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

            # Very dark → heavy smoke/night → severe
            if brightness < 0.30:
                return 'Severe Damage'
            # Dominant red → fire / structural damage
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
