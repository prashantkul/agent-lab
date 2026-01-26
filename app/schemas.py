"""Pydantic schemas for request/response validation."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator


class ModuleBase(BaseModel):
    """Base module schema."""

    name: str
    week_number: int
    short_description: Optional[str] = None
    detailed_description: Optional[str] = None
    learning_objectives: Optional[list[str]] = None
    prerequisites: Optional[list[str]] = None
    expected_outcomes: Optional[str] = None
    estimated_time_minutes: Optional[int] = None
    drive_file_id: str
    instructions: Optional[str] = None
    homework_instructions: Optional[str] = None
    grading_criteria: Optional[str] = None
    max_points: int = 100
    max_reviewers: int = 10
    max_students: Optional[int] = None


class ModuleCreate(ModuleBase):
    """Schema for creating a module."""

    pass


class ModuleUpdate(BaseModel):
    """Schema for updating a module."""

    name: Optional[str] = None
    week_number: Optional[int] = None
    visibility: Optional[str] = None
    short_description: Optional[str] = None
    detailed_description: Optional[str] = None
    learning_objectives: Optional[list[str]] = None
    prerequisites: Optional[list[str]] = None
    expected_outcomes: Optional[str] = None
    estimated_time_minutes: Optional[int] = None
    drive_file_id: Optional[str] = None
    instructions: Optional[str] = None
    homework_instructions: Optional[str] = None
    grading_criteria: Optional[str] = None
    max_points: Optional[int] = None
    max_reviewers: Optional[int] = None
    max_students: Optional[int] = None


class ModuleResponse(ModuleBase):
    """Schema for module response."""

    id: int
    visibility: str
    drive_modified_time: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    reviewer_count: int = 0
    student_count: int = 0

    class Config:
        from_attributes = True


class SubmissionCreate(BaseModel):
    """Schema for creating a submission."""

    github_link: str
    comments: str
    clarity_rating: Optional[int] = None
    difficulty_rating: Optional[int] = None
    time_spent_minutes: Optional[int] = None

    @field_validator("github_link")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Validate GitHub URL format."""
        import re

        pattern = r"^https://github\.com/[\w-]+/[\w.-]+/?$"
        if not re.match(pattern, v):
            raise ValueError("Invalid GitHub repository URL")
        return v.rstrip("/")

    @field_validator("clarity_rating", "difficulty_rating")
    @classmethod
    def validate_rating(cls, v: Optional[int]) -> Optional[int]:
        """Validate rating is between 1 and 5."""
        if v is not None and (v < 1 or v > 5):
            raise ValueError("Rating must be between 1 and 5")
        return v


class SubmissionResponse(BaseModel):
    """Schema for submission response."""

    id: int
    user_id: int
    module_id: int
    submission_type: str
    github_link: str
    comments: str
    clarity_rating: Optional[int] = None
    difficulty_rating: Optional[int] = None
    time_spent_minutes: Optional[int] = None
    submitted_at: datetime

    class Config:
        from_attributes = True


class GradeResponse(BaseModel):
    """Schema for grade response."""

    id: int
    submission_id: int
    total_points: Optional[Decimal] = None
    max_points: int
    percentage: Optional[Decimal] = None
    letter_grade: Optional[str] = None
    score_breakdown: Optional[dict] = None
    automated_feedback: Optional[str] = None
    manual_feedback: Optional[str] = None
    strengths: Optional[list[str]] = None
    improvements: Optional[list[str]] = None
    status: str
    graded_at: Optional[datetime] = None
    graded_by: Optional[str] = None

    class Config:
        from_attributes = True


class ManualGradeCreate(BaseModel):
    """Schema for manual grading."""

    total_points: Decimal
    manual_feedback: Optional[str] = None
    strengths: Optional[list[str]] = None
    improvements: Optional[list[str]] = None


class UserResponse(BaseModel):
    """Schema for user response."""

    id: int
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    role: str
    selected_module_id: Optional[int] = None
    student_id: Optional[str] = None
    cohort: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    """Schema for updating user role."""

    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is valid."""
        valid_roles = ["reviewer", "student", "admin"]
        if v not in valid_roles:
            raise ValueError(f"Role must be one of: {', '.join(valid_roles)}")
        return v


class VisibilityUpdate(BaseModel):
    """Schema for updating module visibility."""

    visibility: str

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        """Validate visibility is valid."""
        valid = ["draft", "pilot_review", "active", "archived"]
        if v not in valid:
            raise ValueError(f"Visibility must be one of: {', '.join(valid)}")
        return v
