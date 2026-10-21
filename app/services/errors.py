class ApiError(Exception):
    """Error de negocio con mensaje en español apto para mostrarse al participante."""

    def __init__(self, message: str, status: int = 400, code: str = "bad_request", fields: dict | None = None, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.fields = fields or {}
        self.extra = extra or {}

    def to_dict(self) -> dict:
        body = {"error": {"code": self.code, "message": self.message}}
        if self.fields:
            body["error"]["fields"] = self.fields
        body["error"].update(self.extra)
        return body
