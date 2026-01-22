# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in Spark, please report it responsibly by emailing:

**matthew@digital-thought.org**

### What to Include

Please include the following information in your report:

1. **Description**: Clear description of the vulnerability
2. **Impact**: Potential impact and severity assessment
3. **Steps to Reproduce**: Detailed steps to reproduce the issue
4. **Affected Versions**: Which versions are affected
5. **Suggested Fix**: If you have one (optional)

### What to Expect

- **Acknowledgement**: Within 48 hours of your report
- **Initial Assessment**: Within 7 days
- **Status Updates**: At least every 14 days until resolution
- **Resolution Timeline**: Depends on severity and complexity

### Severity Levels

| Severity | Response Time | Examples |
|----------|---------------|----------|
| Critical | 24-48 hours | Remote code execution, data breach |
| High | 7 days | Authentication bypass, privilege escalation |
| Medium | 30 days | Information disclosure, denial of service |
| Low | 90 days | Minor information leakage, best practice violations |

### Safe Harbour

We consider security research conducted in accordance with this policy to be:

- Authorised concerning any applicable anti-hacking laws
- Authorised concerning any relevant anti-circumvention laws
- Exempt from restrictions in our Terms of Service that would interfere with conducting security research

We will not pursue civil action or initiate a complaint to law enforcement for accidental, good-faith violations of this policy.

### Recognition

We appreciate the security research community's efforts in helping keep Spark secure. With your permission, we will acknowledge your contribution in our release notes.

## Security Features

Spark includes several built-in security features:

### Prompt Security Inspection
- Pattern-based detection of prompt injection attempts
- LLM-based semantic analysis (strict mode)
- Configurable actions: block, warn, sanitise, log

### Access Control
- Tool permission system with user approval
- Per-conversation permission isolation
- Filesystem path validation and traversal prevention

### Audit Logging
- Complete MCP transaction logging
- User action tracking via user_guid
- Export capability for compliance

### Authentication
- AWS SSO integration (recommended)
- One-time authentication codes for web interface
- Session timeout management

### Data Protection
- Multi-user data isolation
- SSL/TLS for web interface
- Secure credential handling

## Security Best Practices

When deploying Spark:

1. **Enable prompt inspection** in production environments
2. **Use tool permissions** (don't enable auto_approve)
3. **Restrict filesystem access** to minimum necessary paths
4. **Use AWS SSO** instead of static credentials
5. **Keep web interface localhost-only** unless properly secured
6. **Review audit logs** regularly
7. **Keep Spark updated** to receive security patches

## Known Security Considerations

### Web Interface
- Self-signed certificates generate browser warnings
- Designed for localhost access only
- Not recommended for internet exposure without additional security

### Tool Execution
- MCP tools execute with Spark's permissions
- Filesystem tools restricted to configured paths
- Tool permission prompts can be bypassed with auto_approve

### Data Storage
- Conversations stored in plaintext in database
- Credentials should not be stored in config files
- Audit logs may contain sensitive tool inputs/outputs

## Contact

For security-related inquiries:
- Email: matthew@digital-thought.org
- Subject line: [SECURITY] Spark - Brief Description

For general questions, please use GitHub Issues or Discussions.
