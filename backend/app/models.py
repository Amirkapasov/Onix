"""Модели запроса/ответа строго по contracts/api.md."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Filters(BaseModel):
    with_kids: bool | None = None
    accessibility: bool | None = None
    group_size: int | None = None
    time_budget_min: int | None = Field(default=None, ge=5, le=24 * 60)
    indoor_only: bool | None = None
    categories: list[str] = []


class RecommendRequest(BaseModel):
    query: str = Field(default="", max_length=1000)
    location: Location | None = None
    location_label: str | None = Field(default=None, max_length=200)
    client_time: str | None = None
    lang: Literal["ru", "kk", "en"] | None = None
    mode: Literal["walk", "car", "transit"] = "walk"
    filters: Filters = Filters()
    want_route: bool = False


class ContextUsed(BaseModel):
    location: str
    time: str
    weather: str
    mode: str
    radius_m: int
    filters: list[str]
    data_note: str


class ParsedIntent(BaseModel):
    intent: str
    time_budget_min: int | None
    companions: str
    constraints: list[str]
    keywords: list[str]


class OpenStatus(BaseModel):
    state: Literal["open", "closed", "unknown"]
    confidence: Literal["high", "medium", "low"]
    label: str
    source: str | None = None


class SourceRef(BaseModel):
    name: str
    url: str | None = None


class Recommendation(BaseModel):
    poi_id: str
    name: str
    category: str
    lat: float
    lon: float
    distance_m: int
    travel_min: int
    visit_min: list[int]
    why: str
    what_to_do: str
    open_status: OpenStatus
    source_type: Literal["poi_data"] = "poi_data"
    sources: list[SourceRef]
    rating: float | None = None
    badges: list[str] = []


class Idea(BaseModel):
    text: str
    source_type: Literal["generated_idea"] = "generated_idea"


class Leg(BaseModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    distance_m: int
    minutes: int

    model_config = {"populate_by_name": True}


class Route(BaseModel):
    stops: list[str]
    legs: list[Leg]
    total_min: int
    geometry: list[list[float]]
    geometry_source: Literal["osrm", "straight_line"]


class LLMInfo(BaseModel):
    provider: str
    model: str | None = None
    latency_ms: int = 0


class RecommendResponse(BaseModel):
    request_id: str
    context_used: ContextUsed
    parsed_intent: ParsedIntent
    recommendations: list[Recommendation]
    ideas: list[Idea] = []
    route: Route | None = None
    warnings: list[str] = []
    llm: LLMInfo
