MODEL ?= LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
MODEL_B ?= Qwen/Qwen2.5-3B-Instruct
LIMIT ?= 6

.PHONY: offline benchmark benchmark-full benchmark-dual simulation staged down

offline:
	./scripts/phase1-offline-check.sh

benchmark:
	LIMIT=$(LIMIT) ./scripts/run-umdl-benchmark.sh "$(MODEL)"

benchmark-full:
	./scripts/run-umdl-benchmark.sh "$(MODEL)"

benchmark-dual:
	LIMIT=$(LIMIT) ./scripts/run-benchmark-dual.sh "$(MODEL)" "$(MODEL_B)"

simulation:
	./scripts/phase2-stonefish-smoke.sh "$(MODEL)"

staged:
	PHASE1_LIMIT=$(LIMIT) ./scripts/run-staged-validation.sh "$(MODEL)"

down:
	docker compose -f docker-compose.v100.yml --profile benchmark-dual --profile simulation down
