from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from src.constants.enums import Review

class Request(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

class Credentials(Request):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class Upload(Request):
    name: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=160)
    csv_text: str = Field(min_length=1, max_length=2_000_000)

class RunRequest(Request):
    dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    params: dict = Field(default_factory=dict)

class ReviewRequest(Request):
    review: Review
    note: str = Field(min_length=1, max_length=500)
    decision: str = Field(default='', max_length=120)

class ScheduleRequest(RunRequest):
    recipient: str = Field(min_length=1, max_length=100)
    first_at: datetime
    repeat_daily: bool = False

class CalibrationRequest(Request):
    device_id: str = Field(min_length=1, max_length=80)
    device_time: str = Field(min_length=1, max_length=40)
    standard_time: str = Field(min_length=1, max_length=40)

class RecomputeRequest(Request):
    dataset_id: int = Field(gt=0)
