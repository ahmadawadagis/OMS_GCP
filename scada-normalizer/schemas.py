# scada-normalizer/schemas.py
from pydantic import BaseModel, validator
from typing import Optional

class RawScadaEvent(BaseModel):
    device_id: str
    status: str
    timestamp: str
    source: Optional[str] = "SCADA"

    @validator('status')
    def validate_status(cls, v):
        if v not in ("ON", "OFF"):
            raise ValueError('status must be "ON" or "OFF"')
        return v