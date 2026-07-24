import os
import sys

# Insert project root directory into sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app as flask_app

class VercelWSGIAdapter:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/api/index'):
            environ['PATH_INFO'] = path[10:] or '/'
        elif path.startswith('/api'):
            environ['PATH_INFO'] = path[4:] or '/'
        return self.app(environ, start_response)

# Vercel entrypoint instance
app = VercelWSGIAdapter(flask_app)
