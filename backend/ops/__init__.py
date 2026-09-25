"""Operational tooling that runs OUTSIDE the API process (scheduled checks, probes). Nothing under
app/ imports this package, so it can never widen the API's attack surface or dependency set.
"""
