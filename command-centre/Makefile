.PHONY: run up down build pack clean check

run:
	python3 main.py

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

pack:
	./scripts/pack_bro.sh

check:
	python3 -m py_compile main.py server.py core/routing.py core/debate.py core/safety.py core/adversarial/providers.py core/adversarial/debate.py
	python3 -m unittest discover -s tests -v

clean:
	rm -rf __pycache__ core/__pycache__ tests/__pycache__ data/*.db data/*.db-shm data/*.db-wal
