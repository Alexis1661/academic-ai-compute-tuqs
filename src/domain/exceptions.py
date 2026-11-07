class DomainError(Exception):
    """Base class for all domain exceptions."""
    def __init__(self, message: str, code: str = "ERR_DOMAIN"):
        super().__init__(message)
        self.message = message
        self.code = code


class InvalidTokenCountError(DomainError):
    """Raised when token counts are negative or out of bounds."""
    def __init__(
        self,
        message: str = "Token counts must be non-negative and total must be greater than zero",
    ):
        super().__init__(message, code="ERR_INVALID_TOKEN_COUNT")


class StorageUnavailableError(DomainError):
    """Raised by persistence adapters when the store cannot commit (AD-7: fail closed)."""
    def __init__(self, message: str = "Quota store unavailable; retry later"):
        super().__init__(message, code="ERR_STORAGE_UNAVAILABLE")


class QuotaExceededError(DomainError):
    """
    Raised by the atomic reservation path (Story 8.4, AD-19) when the requested
    tokens cannot be reserved without overdrafting the daily bucket.

    Carries structured rejection details so the HTTP adapter can build a 429 body.
    """
    def __init__(self, remaining_tokens: int, requested_tokens: int):
        self.remaining_tokens = remaining_tokens
        self.requested_tokens = requested_tokens
        super().__init__(
            f"Quota Exceeded: requested {requested_tokens} tokens but only "
            f"{remaining_tokens} remain in the daily bucket",
            code="ERR_QUOTA_EXCEEDED",
        )
