from src.api.rest.app import create_app

app = create_app()

for route in app.routes:
    methods = getattr(route, "methods", "N/A")
    print(f"{methods} {route.path}")
