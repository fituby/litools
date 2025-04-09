# litools
There are several tools, e.g.:
- Public chats — http://127.0.0.1:5000/chat
- Sandbag/Boost analysis — http://127.0.0.1:5000/boost

## Deployment
1. Install the packages from requirements.txt.
2. Run the app:
    ```bash
    python app.py

    # or customize the host, port, and app URL
    HOST=127.0.0.1 PORT=5000 APP_URL=https://some.website.org python app.py
    ```

## Test docker build locally

```bash
docker build -t litools .

docker run --rm -p 5000:5000 litools
```

## Feedback
Any suggestions for possible improvements and bug reports are welcome.
