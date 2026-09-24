"""Controller laboratory: one contract, several selection policies.

A controller chooses which eligible candidate runs next. It owns nothing else:
candidate eligibility, authorization, budgets, dispatch and recording stay with
the host, and every controller in this package receives the same eligible
candidates, the same feature schema and the same feedback definition, so a
comparison between two of them is a comparison of selection policy and not of
privileges.

`make_controller` is the ordinary construction path and it builds frozen
instances: learning is off unless a research caller passes `learn=True`
explicitly. Local controller learning updates this package's own small weight
tables; it does not fine-tune any language model.
"""

from .baselines import LegacyRankingController, PriorityController
from .linucb import LinUcbController
from .mb import MushroomBodyController
from .plasticity import PlasticMbController

_FACTORIES = {
    "priority": lambda seed, learn: PriorityController(),
    "legacy": lambda seed, learn: LegacyRankingController(),
    "linucb": lambda seed, learn: LinUcbController(learn=learn, seed=seed),
    # The static sparse controller has no learned weights; `learn` is accepted
    # by the factory signature and has nothing to switch on here.
    "mb": lambda seed, learn: MushroomBodyController(seed=seed),
    "mb-plastic": lambda seed, learn: PlasticMbController(seed=seed, learn=learn),
}


def controller_names():
    """The selectable controller names, in stable order."""
    return sorted(_FACTORIES)


def make_controller(name, *, seed=0, learn=False):
    """Build a controller by name. Ordinary callers leave `learn` at False."""
    try:
        factory = _FACTORIES[name]
    except KeyError:
        raise ValueError(f"unknown controller {name!r}; "
                         f"known: {', '.join(controller_names())}") from None
    return factory(seed, learn)
