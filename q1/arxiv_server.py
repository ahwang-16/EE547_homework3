import json
import os
import re
import sys
import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DATA_DIR = 'sample_data'
papers_data = []
corpus_data = {}

try:
  with open(os.path.join(DATA_DIR, 'papers.json'), 'r') as f:
    papers_data = json.load(f)
  with open(os.path.join(DATA_DIR, 'corpus_analysis.json'), 'r') as f:
    corpus_data = json.load(f)
except Exception as e:
  print(f"Warning: Failed to load data gracefully. Starting empty. Error: {e}")


class ArxivServerHandler(BaseHTTPRequestHandler):
  def log_message(self, format, *args):
    pass

  def custom_log(self, status_code, result_count=None):
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_phrase = self.responses.get(status_code, [str(status_code)])[0]

    if result_count is not None:
      print(f"[{dt}] GET {self.path} - {status_code} {status_phrase} ({result_count} results)")
    else:
      print(f"[{dt}] GET {self.path} - {status_code} {status_phrase}")

  def send_json_response(self, status_code, payload, result_count=None):
    self.send_response(status_code)
    self.send_header('Content-type', 'application/json')
    self.end_headers()
    self.wfile.write(json.dumps(payload).encode('utf-8'))
    self.custom_log(status_code, result_count)

  def do_GET(self):
    try:
      parsed_url = urlparse(self.path)
      path = parsed_url.path

      if path == '/papers':
        summary = [{
          "arxiv_id": p.get("arxiv_id"),
          "title": p.get("title"),
          "authors": p.get("authors"),
          "categories": p.get("categories")
        } for p in papers_data]
        self.send_json_response(200, summary, result_count=len(summary))

      elif re.match(r'^/papers/[\w.\-]+$', path):
        arxiv_id = path.split('/')[-1]
        paper = next((p for p in papers_data if p.get("arxiv_id") == arxiv_id), None)

        if paper:
          details = {
            "arxiv_id": paper.get("arxiv_id"),
            "title": paper.get("title"),
            "authors": paper.get("authors"),
            "abstract": paper.get("abstract"),
            "categories": paper.get("categories"),
            "published": paper.get("published"),
            "abstract_stats": {
              "total_words": paper.get("abstract_stats", {}).get("total_words"),
              "unique_words": paper.get("abstract_stats", {}).get("unique_words"),
              "total_sentences": paper.get("abstract_stats", {}).get("total_sentences")
            }
          }
          self.send_json_response(200, details)
        else:
          self.send_json_response(404, {"error": "Paper not found"})

      elif path == '/search':
        query_params = parse_qs(parsed_url.query)

        if 'q' not in query_params or not query_params['q'][0].strip():
          self.send_json_response(400, {"error": "Malformed search query. 'q' parameter is required."})
          return

        query_str = query_params['q'][0].lower()
        query_terms = query_str.split()
        results = []

        for p in papers_data:
          title = p.get("title", "").lower()
          abstract = p.get("abstract", "").lower()

          all_terms_found = True
          total_score = 0
          matches = set()

          for term in query_terms:
            t_count = title.count(term)
            a_count = abstract.count(term)

            if t_count == 0 and a_count == 0:
              all_terms_found = False
              break

            total_score += (t_count + a_count)
            if t_count > 0: matches.add("title")
            if a_count > 0: matches.add("abstract")

          if all_terms_found and query_terms:
            results.append({
              "arxiv_id": p.get("arxiv_id"),
              "title": p.get("title"),
              "match_score": total_score,
              "matches_in": list(matches)
            })

        self.send_json_response(200, {"query": query_params['q'][0], "results": results}, result_count=len(results))

      elif path == '/stats':
        top_10 = [{"word": w["word"], "frequency": w["frequency"]}
                  for w in corpus_data.get("top_50_words", [])[:10]]

        stats = {
          "total_papers": corpus_data.get("papers_processed"),
          "total_words": corpus_data.get("corpus_stats", {}).get("total_words"),
          "unique_words": corpus_data.get("corpus_stats", {}).get("unique_words_global"),
          "top_10_words": top_10,
          "category_distribution": corpus_data.get("category_distribution")
        }
        self.send_json_response(200, stats)

      else:
        self.send_json_response(404, {"error": "Endpoint not found"})

    except Exception as e:
      self.send_json_response(500, {"error": f"Internal server error: {str(e)}"})


if __name__ == '__main__':
  port = 8080
  if len(sys.argv) > 1:
    try:
      port = int(sys.argv[1])
    except ValueError:
      print(f"Invalid port: {sys.argv[1]}. Using default 8080.")

  server = ThreadingHTTPServer(('0.0.0.0', port), ArxivServerHandler)
  print(f"Server running on port {port}. Press Ctrl+C to stop.")
  server.serve_forever()
