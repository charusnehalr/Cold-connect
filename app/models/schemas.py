from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.utcnow()


def _uuid() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoleCategory(str, Enum):
    FOUNDER = "founder"
    ENGINEERING_LEADER = "engineering_leader"
    RECRUITER = "recruiter"
    SENIOR_ENGINEER = "senior_engineer"
    TECH_LEAD = "tech_lead"


class PersonStatus(str, Enum):
    RESEARCHED = "researched"
    SENT = "sent"
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    SKIPPED = "skipped"


class CompanyStatus(str, Enum):
    RESEARCHED = "researched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class Company(BaseModel):
    name: str
    linkedin_url: str
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    description: Optional[str] = None
    recent_posts: list[str] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=_now)


class Person(BaseModel):
    name: str
    title: str
    linkedin_url: str
    location: Optional[str] = None
    about: Optional[str] = None
    experience_summary: Optional[str] = None
    recent_posts: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    role_category: RoleCategory = RoleCategory.SENIOR_ENGINEER
    fetch_error: bool = False


class GeneratedMessage(BaseModel):
    text: str
    angle: str = ""


class PersonResult(BaseModel):
    person: Person
    message: GeneratedMessage
    why_connect: str = ""


# ---------------------------------------------------------------------------
# Tracker models
# ---------------------------------------------------------------------------

class TrackedPerson(BaseModel):
    id: str = Field(default_factory=_uuid)
    person: Person
    message: GeneratedMessage
    why_connect: str = ""
    status: PersonStatus = PersonStatus.RESEARCHED
    sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    notes: str = ""


class TrackedCompany(BaseModel):
    id: str = Field(default_factory=_uuid)
    company: Company
    people: list[TrackedPerson] = Field(default_factory=list)
    status: CompanyStatus = CompanyStatus.RESEARCHED
    searched_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    company: Company
    people: list[PersonResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# User config
# ---------------------------------------------------------------------------

class UserConfig(BaseModel):
    name: str = ""
    bio: str = ""
    target_roles: list[str] = Field(default_factory=lambda: [
        "founder OR co-founder OR CEO",
        "CTO OR VP engineering OR head of engineering",
        "recruiter OR talent acquisition OR hiring manager",
        "senior engineer OR staff engineer OR principal engineer",
        "tech lead OR engineering manager",
    ])
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
