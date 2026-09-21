from pathlib import Path


def test_canonical_spec_copy_matches_authority() -> None:
    assert Path("spec.md").read_bytes() == Path("spec(4).md").read_bytes()
