from personal_website_app import create_app, run_app

app = create_app()

if __name__ == "__main__":
    run_app(app, host="127.0.0.1", port=8080)
