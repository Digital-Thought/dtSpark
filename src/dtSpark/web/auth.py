"""
Authentication manager for web interface.

Implements authentication code system with secure hashing.
Codes are reusable to allow re-authentication after session expiration.

"""

import secrets
import string
import hashlib
from typing import Optional
from datetime import datetime


class AuthManager:
    """
    Manages authentication for the web interface using authentication codes.

    Security features:
    - Generates cryptographically secure random codes
    - Stores hashed codes (not plaintext)
    - Code can be reused for session re-authentication (required for session expiry)
    - Code generation logged with timestamp
    - Use count tracked for audit purposes

    Note:
        Since this is a local-only application (127.0.0.1), the code can be
        reused to allow users to re-authenticate after session expiration.
        The code is displayed in the console and remains valid for the
        lifetime of the application.
    """

    def __init__(self):
        """Initialise the authentication manager."""
        self._code_hash: Optional[str] = None
        self._use_count: int = 0
        self._generated_at: Optional[datetime] = None
        self._last_used_at: Optional[datetime] = None

    def generate_code(self, length: int = 8) -> str:
        """
        Generate a new authentication code.

        Args:
            length: Length of the code (default: 8 characters)

        Returns:
            The generated code (plaintext, for display to user)

        Note:
            The code is stored as a SHA-256 hash internally for security.
        """
        # Generate cryptographically secure random code
        alphabet = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(alphabet) for _ in range(length))

        # Store hash of code (not plaintext)
        self._code_hash = self._hash_code(code)
        self._use_count = 0
        self._generated_at = datetime.now()
        self._last_used_at = None

        return code

    def validate_code(self, code: str) -> bool:
        """
        Validate an authentication code.

        Args:
            code: The code to validate

        Returns:
            True if code is valid, False otherwise

        Note:
            The code can be reused for session re-authentication after
            session expiration. Use count is tracked for audit purposes.
        """
        # Check if code exists
        if self._code_hash is None:
            return False

        # Validate code by comparing hashes
        if self._hash_code(code) == self._code_hash:
            # Track usage for audit purposes
            self._use_count += 1
            self._last_used_at = datetime.now()
            return True

        return False

    def is_code_used(self) -> bool:
        """
        Check if the current code has been used at least once.

        Returns:
            True if code has been used, False otherwise
        """
        return self._use_count > 0

    def get_use_count(self) -> int:
        """
        Get the number of times the code has been used.

        Returns:
            Number of times the code has been used for authentication
        """
        return self._use_count

    def get_last_used_at(self) -> Optional[datetime]:
        """
        Get the timestamp when the code was last used.

        Returns:
            Datetime when code was last used, or None if never used
        """
        return self._last_used_at

    def get_generated_at(self) -> Optional[datetime]:
        """
        Get the timestamp when the code was generated.

        Returns:
            Datetime when code was generated, or None if no code exists
        """
        return self._generated_at

    def reset(self):
        """
        Reset the authentication state.

        This clears the current code and allows a new one to be generated.
        Used when restarting the web server.
        """
        self._code_hash = None
        self._use_count = 0
        self._generated_at = None
        self._last_used_at = None

    @staticmethod
    def _hash_code(code: str) -> str:
        """
        Hash a code using SHA-256.

        Args:
            code: The code to hash

        Returns:
            Hexadecimal string representation of the hash
        """
        return hashlib.sha256(code.encode('utf-8')).hexdigest()
