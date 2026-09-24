"""Cross-run priors: a profile-keyed bank of what earlier episodes learned.

Episode weights (plasticity.py) die with their run. What survives, when a
research configuration says so, is a small sanitized aggregate per target
profile: for each hypothesis family, how episodes ended and what the mean
modulation was. The bank is advisory -- a later run may read it as a prior
term -- and it stores aggregates, deliberately not per-synapse weights.

Both key rules exist because of a recorded incident in the originating
implementation, kept here as a teaching exercise. Its fold gate accepted only
hex-digest profile keys, while the only production producer of profile keys
emitted a colon-joined descriptor; every real fold was quietly a no-op, and
the bank stayed empty in production while its tests passed on hand-built keys.
`HEX_ONLY` reproduces that gate; `DIGESTED` is the corrected rule, which
canonicalizes any nonempty descriptor by digesting it. The lesson walks both.
"""

import hashlib
import re


PRIORS_VERSION = "priors-v1"

_HEX_RE = re.compile(r"^[0-9a-f]{8,64}$")

# The historical gate: only an already-hex key may fold. A descriptor-shaped
# key -- the shape the profile producer actually emits -- is turned away.
HEX_ONLY = "hex-only"

# The corrected rule: any nonempty key is canonicalized to a hex digest, so
# the producer's descriptor format and a pre-digested key both land.
DIGESTED = "digested"


def descriptor_key(profile):
    """The profile-descriptor key shape a fingerprinter naturally produces."""
    return ":".join(f"{k}={profile[k]}" for k in sorted(profile))


class PriorBank:
    """Versioned per-profile aggregates, folded episode by episode."""

    def __init__(self, *, key_rule=DIGESTED):
        if key_rule not in (HEX_ONLY, DIGESTED):
            raise ValueError(f"unknown key rule {key_rule!r}")
        self.key_rule = key_rule
        self._bank = {}

    def _storage_key(self, profile_key):
        if not isinstance(profile_key, str) or not profile_key:
            return None
        if self.key_rule == HEX_ONLY:
            return profile_key if _HEX_RE.match(profile_key) else None
        if _HEX_RE.match(profile_key):
            return profile_key
        return hashlib.sha256(profile_key.encode("utf-8")).hexdigest()

    def fold_episode(self, profile_key, family_outcomes):
        """Fold one finished episode's per-family aggregates into the bank.

        `family_outcomes` maps family -> {"episodes": 1, "mean_modulation": x,
        "signatures": {name: count}}. Returns a report naming how many family
        rows folded and under which storage key; a key the rule turns away
        folds nothing and says so, which is the observable the lesson's defect
        exercise reads.
        """
        key = self._storage_key(profile_key)
        if key is None:
            return {"folded": 0, "stored_key": None,
                    "reason": f"profile key rejected by the {self.key_rule} rule"}
        rows = self._bank.setdefault(key, {"version": PRIORS_VERSION, "families": {}})
        folded = 0
        for family, aggregate in sorted(family_outcomes.items()):
            row = rows["families"].setdefault(
                family, {"episodes": 0, "mean_modulation": 0.0, "signatures": {}})
            episodes = row["episodes"] + int(aggregate.get("episodes", 1))
            weight_old = row["episodes"] / episodes if episodes else 0.0
            row["mean_modulation"] = round(
                row["mean_modulation"] * weight_old
                + float(aggregate.get("mean_modulation", 0.0)) * (1 - weight_old), 9)
            row["episodes"] = episodes
            for signature, count in aggregate.get("signatures", {}).items():
                row["signatures"][signature] = (
                    row["signatures"].get(signature, 0) + int(count))
            folded += 1
        return {"folded": folded, "stored_key": key, "reason": None}

    def load(self, profile_key):
        """The stored aggregates for a profile, or an empty mapping."""
        key = self._storage_key(profile_key)
        if key is None or key not in self._bank:
            return {}
        return {family: dict(row)
                for family, row in self._bank[key]["families"].items()}

    def prior_bonus(self, profile_key, family, *, scale=0.1):
        """A small bounded prior term from the bank: advisory, not authority."""
        row = self.load(profile_key).get(family)
        if not row:
            return 0.0
        bonus = scale * row["mean_modulation"]
        return max(-scale, min(scale, bonus))
