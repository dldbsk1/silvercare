from pydantic import BaseModel

from app.schemas.consents import ConsentType


class MeUserOut(BaseModel):
    id: str
    login_type: str | None


class OnboardingOut(BaseModel):
    consents_completed: bool
    missing_consents: list[ConsentType]
    parent_registered: bool


class MeOut(BaseModel):
    user: MeUserOut
    onboarding: OnboardingOut
    parent_ids: list[str]
