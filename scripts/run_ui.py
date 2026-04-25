import webbrowser
import uvicorn

if __name__ == "__main__":
    url = "http://127.0.0.1:8080/"
    webbrowser.open(url)
    uvicorn.run("localflight.ui.server:app", host="127.0.0.1", port=8080, reload=False)
