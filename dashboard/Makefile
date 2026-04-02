build:
	docker buildx build \
		--build-context common=../common \
		-t dashboard \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 dashboard
