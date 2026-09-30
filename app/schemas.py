from pydantic import BaseModel, Field


class ExtractAttributesIn(BaseModel):
    message_ids: list[int] = Field(min_length=1)
