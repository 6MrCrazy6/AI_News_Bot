from datetime import datetime, timezone
from typing import Optional

from db import get_source_weight

def compute_hours_old(published: datetime) -> float:

    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - published
    return delta.total_seconds() / 3600

def compute_score(url: str, title: str, source_id: str, published: datetime, stars: Optional[int] = 0,
                  upvotes: Optional[int] = 0) -> float:
    stars_val = float(stars or 0)
    upvotes_val = float(upvotes or 0)
    base = stars_val + upvotes_val

    source_weight: Optional[int] = get_source_weight(source_id)
    sw_value = 1 if source_weight is None else float(source_weight)

    hours_old = compute_hours_old(published)
    freshness_bonus = max(0.0, 48.0 - hours_old)

    score = base + sw_value + freshness_bonus
    return round(score, 2)