from ninja import Schema


class HealthOut(Schema):
    database: bool
    release: str
