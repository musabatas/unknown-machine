A production system is down. It has one service, `kestrel`, and it must end up in the mode `serving`.

You operate the system only through the `machine` MCP server, which gives you three tools:

- `status()` shows the current mode of every service.
- `run(service, command)` executes a command on a service. The commands for `kestrel` are `start` and `serve`.
- `finish()` ends the episode.

A command that is not valid in the current mode is refused with an error code and changes nothing. Bring `kestrel` to `serving`, then call `finish()`.

Your score is computed by the system from the final mode of `kestrel`. Nothing you write to disk or say counts.
