build:
	docker buildx build \
		--build-context common=../common \
		-t gist \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 \
		-e ROOT_DOMAIN \
		-e SESSION_SECRET=test \
		-e STORAGE_DIR=/tmp/aeratools \
		gist
