"""
Unit tests for web interface authentication.

Tests the AuthManager class for one-time code generation and validation.

"""

import pytest
from dtSpark.web.auth import AuthManager


class TestAuthManager:
    """Test cases for AuthManager."""

    def test_generate_code(self):
        """Test that code generation works correctly."""
        auth = AuthManager()
        code = auth.generate_code()

        assert code is not None
        assert len(code) == 8
        assert code.isupper()
        assert code.isalnum()

    def test_generate_code_custom_length(self):
        """Test code generation with custom length."""
        auth = AuthManager()
        code = auth.generate_code(length=12)

        assert len(code) == 12

    def test_validate_code_success(self):
        """Test that valid code is accepted."""
        auth = AuthManager()
        code = auth.generate_code()

        assert auth.validate_code(code) is True

    def test_validate_code_case_insensitive(self):
        """Test that code validation is case-insensitive."""
        auth = AuthManager()
        code = auth.generate_code()

        # Test with lowercase version
        assert auth.validate_code(code.lower()) is True

    def test_validate_code_one_time_use(self):
        """Test that code can only be used once."""
        auth = AuthManager()
        code = auth.generate_code()

        # First use should succeed
        assert auth.validate_code(code) is True

        # Second use should fail (code already used)
        assert auth.validate_code(code) is False

    def test_validate_code_wrong_code(self):
        """Test that wrong code is rejected."""
        auth = AuthManager()
        auth.generate_code()

        assert auth.validate_code("WRONGCODE") is False

    def test_is_code_used(self):
        """Test tracking of code usage."""
        auth = AuthManager()
        code = auth.generate_code()

        assert auth.is_code_used() is False

        auth.validate_code(code)

        assert auth.is_code_used() is True

    def test_reset(self):
        """Test that reset clears the code."""
        auth = AuthManager()
        code = auth.generate_code()
        auth.validate_code(code)

        assert auth.is_code_used() is True

        auth.reset()

        assert auth.is_code_used() is False

    def test_get_generated_at(self):
        """Test that timestamp is tracked."""
        auth = AuthManager()

        assert auth.get_generated_at() is None

        auth.generate_code()

        assert auth.get_generated_at() is not None

    def test_validate_without_generation(self):
        """Test that validation fails without code generation."""
        auth = AuthManager()

        assert auth.validate_code("TESTCODE") is False
