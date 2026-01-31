"""
Attack pattern definitions for prompt inspection.

This module contains regex patterns and keyword lists for detecting:
- Prompt injection attempts
- Jailbreak attempts
- Code injection patterns
- Excessive content
- Other security risks


"""

import re
from typing import Dict, List, Tuple, Optional

# Prompt injection patterns - attempts to override system instructions
PROMPT_INJECTION_PATTERNS = [
    r'ignore\s+(previous|all|above|earlier|prior)\s+(instructions?|prompts?|rules?|directives?)',
    r'disregard\s+(previous|all|above|earlier|prior)\s+(instructions?|prompts?|rules?)',
    r'forget\s+(previous|all|above|earlier|prior)\s+(instructions?|prompts?|rules?)',
    r'new\s+(instruction|directive|command|task|role):\s*',
    r'system:\s*(you\s+)?(are|must|should|will)\s+now',
    r'override\s+(previous|all|system)\s+(instructions?|settings?|rules?)',
    r'</s>|<\|im_end\|>|<\|endoftext\|>|<\|system\|>',  # Model control tokens
    r'\[INST\]|\[/INST\]',  # Instruction markers
    r'<\|assistant\|>|<\|user\|>',  # Role markers
]

# Jailbreak patterns - attempts to bypass safety guidelines
JAILBREAK_PATTERNS = [
    r'\b(DAN|Developer\s+Mode|Sudo\s+Mode|God\s+Mode|Admin\s+Mode)\b',
    r'pretend\s+you\s+(are|have)\s+no\s+(restrictions?|limitations?|rules?|ethics?|guidelines?)',
    r'roleplay\s+as\s+(an?\s+)?(unrestricted|unfiltered|uncensored)',
    r'act\s+as\s+if\s+you\s+(have\s+)?no\s+(restrictions?|limitations?|rules?)',
    r'bypass\s+(safety|content|moderation|filter)',
    r'without\s+(any\s+)?(ethical|moral|safety)\s+(concerns?|considerations?|restrictions?)',
    r'evil\s+(ai|assistant|mode)',
    r'jailbreak|jailbroken',
]

# Code injection patterns - malicious code attempts
CODE_INJECTION_PATTERNS = [
    r';\s*rm\s+-rf',
    r';\s*DROP\s+TABLE',
    r';\s*DELETE\s+FROM',
    r'<script[^>]*>.*?</script>',
    r'\$\([^)]+\)|`[^`]+`',  # Command substitution
    r'\|\s*bash|\|\s*sh|\|\s*zsh',
    r'&&\s*(rm|del|format|wget|curl)\s',
    r'eval\s*\(',
    r'exec\s*\(',
    r'system\s*\(',
    r'__import__\s*\(',
]

# PII patterns - potential personally identifiable information
PII_PATTERNS = [
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN pattern
    r'\b\d{16}\b',  # Credit card pattern
    r'\b[A-Z]{2}\d{6,8}\b',  # Passport pattern
    r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',  # IP address
    r'password\s*[:=]\s*\S+',  # Password disclosure
    r'api[_-]?key\s*[:=]\s*\S+',  # API key
    r'secret\s*[:=]\s*\S+',  # Secret disclosure
]

# Excessive repetition pattern
EXCESSIVE_REPETITION_PATTERN = r'(.{10,}?)\1{5,}'  # Same pattern repeated 5+ times


class PatternMatcher:
    """
    Pattern-based detection for prompt security issues.
    """

    def __init__(self):
        """Initialise pattern matcher with compiled regex patterns."""
        self.prompt_injection_regex = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
        self.jailbreak_regex = [re.compile(p, re.IGNORECASE) for p in JAILBREAK_PATTERNS]
        self.code_injection_regex = [re.compile(p, re.IGNORECASE) for p in CODE_INJECTION_PATTERNS]
        self.pii_regex = [re.compile(p, re.IGNORECASE) for p in PII_PATTERNS]
        self.repetition_regex = re.compile(EXCESSIVE_REPETITION_PATTERN, re.IGNORECASE)

    def check_prompt_injection(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check for prompt injection patterns.

        Args:
            text: Text to analyse

        Returns:
            Tuple of (detected, matched_pattern)
        """
        for pattern in self.prompt_injection_regex:
            match = pattern.search(text)
            if match:
                return True, match.group(0)
        return False, None

    def check_jailbreak(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check for jailbreak attempt patterns.

        Args:
            text: Text to analyse

        Returns:
            Tuple of (detected, matched_pattern)
        """
        for pattern in self.jailbreak_regex:
            match = pattern.search(text)
            if match:
                return True, match.group(0)
        return False, None

    def check_code_injection(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check for code injection patterns.

        Args:
            text: Text to analyse

        Returns:
            Tuple of (detected, matched_pattern)
        """
        for pattern in self.code_injection_regex:
            match = pattern.search(text)
            if match:
                return True, match.group(0)
        return False, None

    def check_pii(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check for potential PII exposure.

        Args:
            text: Text to analyse

        Returns:
            Tuple of (detected, matched_pattern)
        """
        for pattern in self.pii_regex:
            match = pattern.search(text)
            if match:
                # Return redacted version
                return True, "[REDACTED]"
        return False, None

    def check_excessive_repetition(self, text: str) -> bool:
        """
        Check for excessive repetition (potential DoS).

        Args:
            text: Text to analyse

        Returns:
            True if excessive repetition detected
        """
        return bool(self.repetition_regex.search(text))

    def scan_all(self, text: str, config: Dict) -> Dict[str, any]:
        """
        Run all configured pattern checks.

        Args:
            text: Text to analyse
            config: Configuration dict with enabled checks

        Returns:
            Dict with scan results
        """
        results = {
            'violations': [],
            'severity': 'none',
            'detected_patterns': []
        }

        self._scan_check(results, config, 'check_prompt_injection', True,
                         self.check_prompt_injection, text, 'prompt_injection', 'high')
        self._scan_check(results, config, 'check_jailbreak', True,
                         self.check_jailbreak, text, 'jailbreak', 'high')
        self._scan_check(results, config, 'check_code_injection', True,
                         self.check_code_injection, text, 'code_injection', 'critical')
        self._scan_check(results, config, 'check_pii', False,
                         self.check_pii, text, 'pii_exposure', 'medium')
        self._scan_check_excessive_length(results, config, text)
        self._scan_check_repetition(results, text)

        return results

    @staticmethod
    def _escalate_severity(current: str, proposed: str) -> str:
        """Return the more severe of two severity levels."""
        order = ['none', 'low', 'medium', 'high', 'critical']
        return proposed if order.index(proposed) > order.index(current) else current

    def _scan_check(self, results: Dict, config: Dict, config_key: str,
                    default_enabled: bool, check_fn, text: str,
                    violation_name: str, severity: str) -> None:
        """Run a single pattern check and update results if a violation is detected."""
        if not config.get(config_key, default_enabled):
            return
        detected, pattern = check_fn(text)
        if detected:
            results['violations'].append(violation_name)
            results['detected_patterns'].append(pattern)
            results['severity'] = self._escalate_severity(results['severity'], severity)

    @staticmethod
    def _scan_check_excessive_length(results: Dict, config: Dict, text: str) -> None:
        """Check for excessive prompt length and update results."""
        if not config.get('check_excessive_length', True):
            return
        max_length = config.get('max_prompt_length', 50000)
        if len(text) > max_length:
            results['violations'].append('excessive_length')
            results['detected_patterns'].append(f'Length: {len(text)} > {max_length}')
            if results['severity'] == 'none':
                results['severity'] = 'medium'

    def _scan_check_repetition(self, results: Dict, text: str) -> None:
        """Check for excessive repetition and update results."""
        if self.check_excessive_repetition(text):
            results['violations'].append('excessive_repetition')
            results['detected_patterns'].append('Detected repetitive pattern')
            if results['severity'] == 'none':
                results['severity'] = 'low'
