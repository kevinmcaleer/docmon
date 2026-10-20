# docmon listener

Not built yet; tracked in [#3](https://github.com/kevinmcaleer/docmon/issues/3).

It will receive agent broadcasts on UDP 50505 (see
[docs/message-format.md](../docs/message-format.md)), keep the current state
per node, mark a node stale after about three missed beats, and serve a small
web page and JSON API.
