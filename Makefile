lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy .

run:
	uvicorn app.main:app --reload

validate: lint typecheck