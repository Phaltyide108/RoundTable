# Security

Roundtable is local-only by design:

- The MCP server talks to apps over stdio on your computer. It opens no network port.
- The dashboard (`rt ui`) listens on 127.0.0.1 only, checks the Host header, refuses cross-site requests, and requires a per-session token for every action.
- Proof commands come only from the plan you approved at `rt plan lock`, never from model messages.
- Text written by one model is shown to the others marked as data, not instructions.

The seat rules (leases, the commit guard, refusing human-only commands from a seat's working copy) prevent mix-ups between cooperating models. They are not a sandbox: any program with shell access to your computer, including a coding agent, can do what you can.

## Reporting a problem

Please open a private security advisory on the repository's GitHub page (Security tab, "Report a vulnerability"), or an issue without exploit details asking for a private contact. Include the Roundtable version (`rt --version`) and your OS.
