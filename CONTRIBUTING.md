# Contributing Guidelines

Thank you for your interest in contributing to Self-improving Physical AI!

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests locally
5. Commit with a descriptive message
6. Push and open a Pull Request

## Development Setup

See the [README](README.md) for prerequisites and installation instructions.

## Security Practices for Contributors

- **Never commit credentials** — bot tokens, API keys, or passwords must not appear in code or configs
- **Use `.gitignore`** — sensitive configuration files are excluded; verify before committing
- **Validate inputs** — all user-facing parameters must be validated with proper error handling
- **Docker security** — do not disable container isolation or run with `--privileged` unless absolutely necessary
- **Review outputs** — simulation screenshots or USD files may contain environment-specific data; review before including in PRs

## Shared Responsibility

When deploying on AWS, security is a shared responsibility between AWS and the customer. AWS secures the infrastructure; you secure your applications, data, and access controls. See the [Security Considerations](README.md#security-considerations) section in the README.

## Code Style

- Python: Follow PEP 8
- Shell: Use `set -euo pipefail` in bash scripts
- Documentation: Use clear, concise language

## Reporting Security Issues

If you discover a potential security issue in this project, please notify AWS/Amazon Security via the [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). **Do not** create a public GitHub issue for security vulnerabilities.

## License

By contributing, you agree that your contributions will be licensed under the MIT-0 License.
