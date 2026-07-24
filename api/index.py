import os
import sys

# Insert project root directory into sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app

class PrefixMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/api/index'):
            environ['PATH_INFO'] = path[10:] or '/'
        elif path.startswith('/api'):
            environ['PATH_INFO'] = path[4:] or '/'
        return self.wsgi_app(environ, start_response)

# Attach middleware to Flask wsgi_app while keeping `app` as Flask object
app.wsgi_app = PrefixMiddleware(app.wsgi_app)
