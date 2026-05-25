from personal_website_app import create_app, run_app

#Create and run application instance using the factory function and run_app function defined in __init__.py
app = create_app()

if __name__ == "__main__":
    run_app(app, host="0.0.0.0", port=8080)
