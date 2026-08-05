"""Exceptions partagées par les collecteurs."""


class QuotaExhausted(RuntimeError):
    """Le fournisseur de scraping refuse de servir : crédits épuisés / abonnement suspendu.

    Inutile de réessayer dans la même exécution : on interrompt la collecte et on
    remonte ce qui a déjà été récupéré (`rows`, `errors`, `per_source`) pour que le
    pipeline puisse geler les communes manquantes plutôt que tout jeter."""

    def __init__(self, message, rows=None, errors=None, per_source=None):
        super().__init__(message)
        self.rows = rows or []
        self.errors = errors or []
        self.per_source = per_source or {}
