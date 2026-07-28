from pydantic import BaseModel, field_validator


class URLIn(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def strip_url(cls, v: str) -> str:
        return v.strip()


class DownloadRequest(BaseModel):
    url: str
    format_id: str
    audio_only: bool = False
    filename_hint: str | None = None

    @field_validator("url")
    @classmethod
    def strip_url(cls, v: str) -> str:
        return v.strip()


class FormatOut(BaseModel):
    format_id: str
    ext: str
    resolution: str | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    tbr: float | None = None
    note: str | None = None
    kind: str  # "video" (has audio+video), "video_only", "audio"


class MediaInfoOut(BaseModel):
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    extractor: str
    webpage_url: str
    formats: list[FormatOut]


class TaskStatusOut(BaseModel):
    task_id: str
    status: str  # queued | downloading | processing | finished | error
    percent: float = 0.0
    speed: str | None = None
    eta: str | None = None
    filename: str | None = None
    error: str | None = None
