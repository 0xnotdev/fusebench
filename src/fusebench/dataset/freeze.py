"""Freeze boundary kept deliberately inaccessible before CP-13."""


class FreezeNotAuthorized(RuntimeError):
    """The user has not authorized creation of the frozen test set."""


def create_test_dataset(seed: int) -> None:
    """Refuse all test-set creation until the separately authorized freeze checkpoint."""

    del seed
    raise FreezeNotAuthorized("CP-13 freeze has not been authorized")
