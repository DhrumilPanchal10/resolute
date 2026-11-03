from dataclasses import dataclass

from resolute.config import settings


@dataclass(frozen=True)
class Route:
    model: str  # LiteLLM model string, e.g. "gemini/gemini-1.5-flash"


# Ordered fallback lists per tier.  First entry is preferred; subsequent entries
# are tried in order when the previous one returns a rate-limit or 5xx.
# Model names come from config — never hardcoded.
TIER_ROUTES: dict[str, list[Route]] = {
    "small": [
        Route(model=settings.model_small),
        Route(model=settings.model_strong),  # degrade to strong on small exhaustion
    ],
    "strong": [
        Route(model=settings.model_strong),
    ],
    "judge": [
        Route(model=settings.model_judge),
        Route(model=settings.model_strong),
    ],
}


def routes_for_tier(tier: str) -> list[Route]:
    """Return the ordered fallback route list for the given model tier."""
    return TIER_ROUTES.get(tier, [Route(model=settings.model_small)])
