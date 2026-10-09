"""Values that cross a boundary are immutable once built."""

import pytest
from pydantic import ValidationError

from app.main import STATUS_FOR
from app.schemas import SiteIn, StatusChange, WorkOrderIn
from app.models import Status


@pytest.mark.parametrize("model,field,value", [
    (SiteIn(name="Lobby"), "name", "Other"),
    (WorkOrderIn(site_id=1, title="Fix"), "title", "Other"),
    (StatusChange(status=Status.done), "status", Status.open),
])
def test_request_bodies_are_frozen(model, field, value):
    with pytest.raises(ValidationError):
        setattr(model, field, value)


def test_error_to_status_mapping_is_read_only():
    with pytest.raises(TypeError):
        STATUS_FOR[KeyError] = 500  # type: ignore[index]
