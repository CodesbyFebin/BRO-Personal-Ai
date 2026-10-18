#!/usr/bin/env python3
"""BRO local HTTP control plane entry point."""
from http.server import ThreadingHTTPServer
from server import HOST, PORT, Handler, init_db

if __name__ == "__main__":
    init_db()
    print(f"BRO Command Center is ready at http://{HOST}:{PORT}")
    print("All tasks remain local; action execution is disabled.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
