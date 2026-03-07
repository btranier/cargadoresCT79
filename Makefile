run-local:
	set -a; source saci.env.example; set +a; ./start.sh

seed:
	python seed_full_topology.py data/active_mapping.csv

poll-once:
	PYTHONPATH=. python -m backend.poller
