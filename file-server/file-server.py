#!/usr/bin/env python3
"""Basic web server built on Python's standard-library http.server module."""
 
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote
from google.cloud import logging as cloud_logging
from google.api_core.exceptions import NotFound
from google.cloud import pubsub_v1
from google.cloud import storage
import mimetypes
import logging


PROJECT_ID = "project-8aeecca0-4f70-4c6b-8e3"
FORBIDDEN_TOPIC = "forbidden-requests"


BUCKET_NAME = "html-files-for-class"
PREFIX = "pages"
HOST = "0.0.0.0"  # listen on all interfaces so the VM is reachable from outside
PORT = 8080

FORBIDDEN_COUNTRIES = {
    "north korea",
    "iran",
    "cuba",
    "myanmar",
    "iraq",
    "libya",
    "sudan",
    "zimbabwe",
    "syria",
}

# setting up logging to work with google cloud
client = cloud_logging.Client()
client.setup_logging()

storage_client = storage.Client()

publisher = pubsub_v1.PublisherClient()
forbidden_topic_path = publisher.topic_path(PROJECT_ID, FORBIDDEN_TOPIC)

class RequestHandler(BaseHTTPRequestHandler):
    """Handles incoming HTTP requests. Add a do_<METHOD> method per verb you support."""
 
    def _send(self, status, body, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
 
    def do_GET(self):
        filename = unquote(urlsplit(self.path).path).lstrip("/")
        country = self.headers.get("X-country")

        if is_forbidden_country(country):

            event = {
                "status": 403,
                "country": country,
                "filename": filename,
                "method": self.command,
                "client_ip": self.client_address[0],
            }
                    
            logging.critical(
                f"Access denied: request from forbidden country '{country}' for {filename}",
                extra={"json_fields": event}
            )

            publisher.publish(forbidden_topic_path, json.dumps(event).encode("utf-8"))

            self._send(403, "Access denied\n", "text/plain; charset=utf-8")

        else: 
            contents = get_file_from_bucket(filename)
            send_response(self, filename, contents)

 
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        country = self.headers.get("X-country")
        data = json.loads(self.rfile.read(length))
        filename = data.get("filename")

        if is_forbidden_country(country):

            event = {
                "status": 403,
                "country": country,
                "filename": filename,
                "method": self.command,
                "client_ip": self.client_address[0],
            }
                    
            logging.critical(
                f"Access denied: request from forbidden country '{country}' for {filename}",
                extra={"json_fields": event}
            )

            publisher.publish(forbidden_topic_path, json.dumps(event).encode("utf-8"))

            self._send(403, "Access denied\n", "text/plain; charset=utf-8")

        else: 
            contents = get_file_from_bucket(filename)
            send_response(self, filename, contents)


    def __getattr__(self, name):
        # Only called when normal attribute lookup fails, so do_GET and do_POST
        # are found as usual. Any other do_<METHOD> lands here.
        if name.startswith("do_"):
            return self._method_not_implemented
        raise AttributeError(name)

    def _method_not_implemented(self):
        logging.error(
            f"Unsupported HTTP method: {self.command} {self.path}",
            extra={"json_fields": {"status": 501, "method": self.command, "path": self.path}},
        )
        self._send(501, f"Method {self.command} not implemented\n", "text/plain; charset=utf-8")

def is_forbidden_country(country: str | None) -> bool:
    return country is not None and country.strip().lower() in FORBIDDEN_COUNTRIES

def get_file_from_bucket(filename: str) -> None | bytes: 
    blob = storage_client.bucket(BUCKET_NAME).blob(f'{PREFIX}/{filename}')
    try:
        return blob.download_as_bytes()
    except NotFound:
        print(f"The filename {filename} does not exist in GCS")

        logging.warning(
            f"File not found: {filename}",
            extra={"json_fields": {"status": 404, "filename": filename}},
        )

        return None


def send_response(requestHandler: RequestHandler, filename, contents):
    if contents is None:
        requestHandler._send(404, f"File not found: {filename}\n") 
    else: 
        content_type = mimetypes.guess_type(filename)[0] or "text/plain"
        requestHandler._send(200, contents, content_type)
 
def main():
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    print(f"Serving on http://{HOST}:{PORT} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
 
 
if __name__ == "__main__":
    main()