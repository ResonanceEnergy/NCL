.PHONY: quick ci burst-chronos burst-timesfm serve clean

quick:
	python -m future_predictor_council.src.cli \
		--data data/raw/example.csv --freq D --h 14 --windows 3

ci: lint typecheck test quick

lint:
	python -m ruff check src/ tests/

typecheck:
	python -m mypy src/ --ignore-missing-imports

test:
	python -m pytest tests/ -q --tb=short

burst-chronos:
	python -m future_predictor_council.src.cli \
		--data data/raw/example.csv --freq D --h 14 --foundation chronos2

burst-timesfm:
	python -m future_predictor_council.src.cli \
		--data data/raw/example.csv --freq D --h 14 --foundation timesfm

serve:
	uvicorn future_predictor_council.src.serve:app --host 0.0.0.0 --port 8000 --reload

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
