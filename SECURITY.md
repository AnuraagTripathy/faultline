# Security policy

## Reporting a vulnerability

Please report security issues privately — do not open public GitHub issues for exploitable bugs.

Email: security@faultline.dev (replace with your contact before launch)

Include steps to reproduce, impact, and suggested fix if known.

## Supported versions

| Version | Supported |
|---------|-----------|
| 21.x    | Yes       |
| < 21    | Best effort |

## Practices

- Rotate `FAULTLINE_JWT_SECRET` in production
- Never commit API keys or `.env` files
- Use HTTPS in production; set `FAULTLINE_COOKIE_SECURE=1`
- Only load pickle checkpoints you created yourself
