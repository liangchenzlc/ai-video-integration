class ProjectError(Exception):
    """Fixed public error values; never expose an underlying OS exception."""

    def __init__(self, code: str, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        self.message = code
        super().__init__(code)
