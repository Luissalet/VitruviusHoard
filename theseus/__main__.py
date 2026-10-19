import argparse
import uvicorn
import threading
import webbrowser

from .api import create_app


def main():
    parser = argparse.ArgumentParser(description="Local reverse engineering workspace")
    parser.add_argument("--port", type=int, default=5217)
    parser.add_argument("--data")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    uvicorn.run(create_app(args.data, args.port), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
