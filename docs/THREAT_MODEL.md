# Threat Model

## System Overview

This system allows natural language control of robot simulations via a Telegram bot connected to an AI agent (OpenClaw) orchestrating NVIDIA Isaac Sim containers on GPU-enabled cloud instances.

## Assets

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| GPU compute resources | High | NVIDIA L40S/A10G instances — expensive, can be abused for crypto mining |
| Telegram bot token | Confidential | Grants full control of the bot; compromise = full system access |
| Simulation data | Internal | USD scenes, rendered images, robot trajectories |
| Server access | High | EC2 instance with root/sudo access |
| WebRTC stream | Internal | Real-time view of simulation — could expose proprietary scenes |

## Threat Actors

1. **Unauthorized Telegram users** — discover bot username, attempt to send commands
2. **Network attackers** — scan open ports, attempt to access WebRTC stream or exploit services
3. **Supply chain** — compromised Docker images or dependencies
4. **Insider** — authorized user sends destructive commands (intentional or accidental)

## Attack Vectors

| Vector | Impact | Likelihood |
|--------|--------|------------|
| Bot token compromise (leaked in git, config) | Full control of robot commands | Medium |
| Open WebRTC ports (0.0.0.0/0) | Unauthorized viewing of simulation | High if misconfigured |
| Path traversal via script name (`run_sim.sh`) | Arbitrary file read/execute | Low (Docker-contained) |
| Prompt injection via natural language commands | Unintended actions | Medium |
| Docker escape via GPU driver vulnerability | Host compromise | Low |
| Resource exhaustion (continuous sim runs) | Denial of service, cost spike | Medium |

## Existing Mitigations

| Mitigation | Addresses |
|------------|-----------|
| Telegram `dmPolicy: "allowlist"` | Unauthorized users |
| Security Group IP restrictions | Network attackers |
| Docker container isolation | Host compromise |
| `--entrypoint` override (no shell access) | Container escape |
| Headless mode (no GUI exposed) | Unauthorized viewing |
| Script name validation (basename sanitization) | Path traversal |

## Residual Risks

1. **Bot token in config file** — stored in plaintext on disk; mitigate with file permissions (600) and encrypted EBS
2. **No rate limiting** — authorized users can trigger unlimited sim runs; mitigate with command cooldown
3. **No command confirmation** — safety-critical commands (e.g., `move robot`) execute immediately; consider human-in-the-loop for real robot control
4. **Dependency vulnerabilities** — Isaac Sim container includes many packages; mitigate with regular updates
5. **No audit trail** — commands are not persistently logged; implement CloudWatch Logs integration

## Recommendations

- [ ] Move bot token to AWS Secrets Manager
- [ ] Implement command rate limiting (max 10 commands/minute)
- [ ] Add human confirmation for real robot commands
- [ ] Enable CloudWatch Logs for all bot interactions
- [ ] Schedule regular Docker image updates
- [ ] Implement VPC Flow Logs for network monitoring
