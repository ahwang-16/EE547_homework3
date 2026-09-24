## Server Implementation Details

### How `match_score` is computed for a multi-word query
When a search query is received, the string is converted to lowercase and split into individual terms using whitespace. For each paper, the server iterates through every term in the query and counts its occurrences in both the paper's title and abstract (also converted to lowercase for case-insensitive matching). 
If *any* term is entirely missing from both the title and abstract, the paper is excluded from the results. If all terms are present at least once, the total count of all term occurrences across both the title and abstract are summed together to yield the final `match_score`. 

### How the server handles concurrent requests
The server handles concurrent traffic by utilizing `ThreadingHTTPServer` from the standard Python `http.server` library, rather than the base `HTTPServer`. When multiple HTTP requests arrive simultaneously, `ThreadingHTTPServer` spawns a distinct daemon thread to execute the `BaseHTTPRequestHandler` logic for each individual request. This prevents long-running or simultaneous I/O operations from blocking the main server loop, allowing the server to comfortably process well over 10 concurrent requests without queuing delays or timeouts.
