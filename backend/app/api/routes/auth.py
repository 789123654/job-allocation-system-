from fastapi import APIRouter, status

from app import crud
from app.api.deps import CurrentProfileDep, SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/confirm-password-changed", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_changed(actor: CurrentProfileDep, session: SessionDep) -> None:
    crud.confirm_password_changed(session, actor)
