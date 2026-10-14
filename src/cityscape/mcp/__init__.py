"""cityscape MCP server package (DX-05).

A thin wrapper that exposes the existing live FastAPI as MCP tools.
The actual mapping/licensing logic remains exclusively in the API; this
package only invokes it via httpx loopback and returns the normalized JSON 1:1.
Resides intentionally in a separate dependency group (mcp) to keep the
live Docker image lean (T-12-MCP-IMG).
"""
