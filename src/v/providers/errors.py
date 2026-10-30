"""Provider-specific exceptions."""


class ProviderError(Exception):
    """Base class for inference provider errors."""


class ProviderConnectionError(ProviderError):
    """The inference server could not be reached."""


class ProviderAPIError(ProviderError):
    """The inference server returned an unsuccessful response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class ProviderProtocolError(ProviderError):
    """The inference server returned an unexpected response."""


class ModelNotConfiguredError(ProviderError):
    """No conversational model has been selected."""