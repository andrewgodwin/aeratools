build:
	docker buildx build \
		--build-context common=../common \
		-t base64 \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 \
		-e SESSION_SECRET=test \
		base64
