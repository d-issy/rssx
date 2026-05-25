import pytest

from rssx.domain.errors import DomainError
from rssx.domain.value_objects import FeedUrl, FolderName, FolderSelection


def test_feed_url_rejects_blank() -> None:
    with pytest.raises(DomainError):
        FeedUrl.from_raw("  ")


def test_folder_name_trims_value() -> None:
    assert FolderName.from_raw(" News ").value == "News"


def test_folder_selection_parses_new_folder() -> None:
    selection = FolderSelection.from_form("__new", " Tech ")

    assert selection.folder_id is None
    assert selection.new_folder_name is not None
    assert selection.new_folder_name.value == "Tech"
