# Contributing to Spark

Thank you for your interest in contributing to Spark! This document provides guidelines and information for contributors.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behaviour to matthew@digital-thought.org.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up the development environment
4. Create a branch for your changes
5. Make your changes
6. Submit a pull request

## How to Contribute

### Reporting Bugs

- Check existing issues to avoid duplicates
- Use the bug report template
- Include steps to reproduce
- Include expected vs actual behaviour
- Include system information (OS, Python version)

### Suggesting Features

- Check existing issues for similar requests
- Use the feature request template
- Explain the use case clearly
- Consider implementation complexity

### Code Contributions

- Fix bugs from the issue tracker
- Implement approved feature requests
- Improve documentation
- Add or improve tests
- Refactor for better code quality

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Git
- AWS account (for Bedrock testing)

### Installation

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/spark.git
cd spark

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Run tests to verify setup
pytest
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=dtSpark --cov-report=html

# Run specific test file
pytest tests/test_builtin_tools.py

# Run with verbose output
pytest -v
```

## Coding Standards

### Language

- Examples: colour (not color), analyse (not analyze), organise (not organize)

### Style Guide

- Follow [PEP 8](https://pep8.org/) for Python code
- Maximum line length: 120 characters
- Use meaningful variable and function names
- Add docstrings to all public functions and classes

### Code Quality

```python
# Good: Clear, documented function
def calculate_token_usage(messages: List[Dict], model_id: str) -> int:
    """
    Calculate total token usage for a list of messages.

    Args:
        messages: List of message dictionaries with 'content' key
        model_id: The model identifier for tokenisation

    Returns:
        Total token count across all messages
    """
    total = 0
    for message in messages:
        total += count_tokens(message.get('content', ''), model_id)
    return total
```

### Type Hints

Use type hints for function parameters and return values:

```python
from typing import Dict, List, Optional

def get_conversation(
    conversation_id: int,
    include_messages: bool = True
) -> Optional[Dict[str, Any]]:
    ...
```

### Error Handling

- Use specific exception types
- Provide helpful error messages
- Log errors appropriately

```python
try:
    result = perform_operation()
except FileNotFoundError as e:
    logging.error(f"Configuration file not found: {e}")
    raise ConfigurationError(f"Missing config file: {e}") from e
```

### Testing

- Write tests for new functionality
- Maintain or improve code coverage
- Use descriptive test names

```python
def test_token_manager_warns_at_75_percent():
    """Token manager should warn when usage reaches 75% of limit."""
    manager = TokenManager(max_tokens=1000)
    manager.record_usage(750)

    status = manager.check_status()

    assert status == LimitStatus.WARNING_75
```

## Submitting Changes

### Branch Naming

Use descriptive branch names:

- `feature/add-ollama-support`
- `fix/token-counting-error`
- `docs/update-installation-guide`
- `refactor/database-module`

### Commit Messages

Write clear, concise commit messages:

```
Add support for PostgreSQL database backend

- Implement PostgreSQL connection manager
- Add migration scripts for PostgreSQL
- Update configuration documentation
- Add integration tests for PostgreSQL
```

### Pull Request Process

1. **Update documentation** for any changed functionality
2. **Add tests** for new features or bug fixes
3. **Run the test suite** and ensure all tests pass
4. **Update CHANGELOG.md** with your changes
5. **Fill out the PR template** completely
6. **Request review** from maintainers

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] No sensitive data in commits

## Reporting Issues

### Security Issues

**Do not report security vulnerabilities in public issues.**

Please see [SECURITY.md](SECURITY.md) for responsible disclosure guidelines.

### Bug Reports

Use the bug report template and include:

1. **Summary**: Brief description of the issue
2. **Environment**: OS, Python version, Spark version
3. **Steps to reproduce**: Detailed steps to trigger the bug
4. **Expected behaviour**: What should happen
5. **Actual behaviour**: What actually happens
6. **Logs/Screenshots**: Any relevant output

### Feature Requests

Use the feature request template and include:

1. **Problem statement**: What problem does this solve?
2. **Proposed solution**: How should it work?
3. **Alternatives considered**: Other approaches you've thought of
4. **Additional context**: Use cases, examples

## Questions?

- Check the [documentation](docs/)
- Search existing [issues](https://github.com/digital-thought/dtSpark/issues)
- Email: matthew@digital-thought.org

Thank you for contributing to Spark!
