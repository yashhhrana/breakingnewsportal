import os
import sys

# Ensure root folder is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel Serverless Function entry point
if __name__ == "__main__":
    app.run()
