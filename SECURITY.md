# Security

Mia handles mailbox credentials and personal data, so please report problems privately.

- Use GitHub's "Report a vulnerability" (private security advisory) on this repository.
- Do not put credentials, real mail content or personal data in issues or pull requests.

Design points worth knowing: shadow mode and a kill switch by default, credentials are only
read from a local env file, the dashboard listens on localhost with a token and checks the
Host header, and the audit table stores no message text. Details: `docs/adr/`.
