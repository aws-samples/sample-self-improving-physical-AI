# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main branch | ✅ |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Report via the [AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/)
3. Include a clear description, steps to reproduce, and potential impact

We will acknowledge receipt within 72 hours and provide a timeline for resolution.

## Security Best Practices

When using this project:

### Credentials
- Never hardcode bot tokens or API keys in source code
- Use environment variables or AWS Secrets Manager for sensitive configuration
- Rotate tokens every 90 days

### Network
- Always restrict Security Group rules to specific IP addresses
- Never expose WebRTC ports (49100/TCP, 47998/UDP) to `0.0.0.0/0`
- Use VPN or SSH tunnels for production access

### Container
- Verify Docker image digests before pulling
- Set resource limits (memory, CPU) on containers
- Keep container images updated

### Access Control
- Enable Telegram `dmPolicy: "allowlist"` to restrict bot access
- Regularly audit the allowlist
- Monitor bot interaction logs for anomalies

## Scope

This security policy covers the code and documentation in this repository. Third-party dependencies (NVIDIA Isaac Sim, Docker, OpenClaw) have their own security policies.
