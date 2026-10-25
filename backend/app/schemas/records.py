from pydantic import BaseModel


class AudioUploadUrlIn(BaseModel):
    content_type: str = "audio/mp4"


class AudioUploadUrlOut(BaseModel):
    bucket: str
    audio_path: str
    upload_url: str
    token: str
    expires_in_seconds: int
