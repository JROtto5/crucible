# notes service: guide for contributors and agents

## Layout
- `notes/handlers.py`: one function per request type. Each takes the request dict and returns a response dict.
- `notes/paths.py`: path helpers.
- `tests/`: pytest, one test module per source module.

## Rules
- **Paths from callers:** always pass a caller-supplied path through `inside_root()` (notes/paths.py) before any
  filesystem call. Never hand it straight to `open()`, `os.stat()`, `os.remove()` or `os.listdir()`: requests come
  from the network and may contain `..` or an absolute path.
- **Errors:** raise `RequestError` with a short message; never put an absolute filesystem path in it.
- **Style:** type hints on public functions; no print() in library code.
