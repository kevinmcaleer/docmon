"""Shared message format for docmon broadcasts.

Both the agent (which sends) and the listener (which receives) import this
package, so the wire format is defined in exactly one place. See
docs/message-format.md for the human-readable description.
"""

from docmon_schema.message import (
    DEFAULT_MAX_DATAGRAM,
    DEFAULT_PORT,
    OCI_LABELS,
    SCHEMA_VERSION,
    build_messages,
    decode,
    encode,
)

__all__ = [
    "DEFAULT_MAX_DATAGRAM",
    "DEFAULT_PORT",
    "OCI_LABELS",
    "SCHEMA_VERSION",
    "build_messages",
    "decode",
    "encode",
]
